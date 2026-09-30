"""
LightClaw (hermes) — 指标采集器（MetricsCollector）

每个 adapter 进程持一个实例。
职责（对应 §3）：
    - 聚合型指标（连接质量/消息可靠性/定时任务健康）：60s 窗口内存累计，到点打包上报
    - 事件型指标（错误事件）：发生即立即上报
    - 上报失败：转入本地降级缓冲（每 uin 独立一份），恢复后合并补报
    - 进程崩溃：由 crash_guard 统一注册，last-gasp 上报

授权门控：授权粒度是实例级，采集器用一个全局布尔（get_consent_agreed()）统一
门控所有上报入口；未同意（含未决策/已拒绝）时完全不产生任何上报。

⚠️ 每个 uin 的指标必须用该 uin 自己的 apiKey 上报，绝不能把多个 uin 的条目
合并进同一次 HTTP 调用——ai-server 侧按调用方鉴权身份归属所有条目，混用会
导致指标被算到别的租户头上。
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from ..config import (
    METRICS_BATCH_MAX_ITEMS,
    METRICS_BUFFER_FILE_MAX_BYTES,
    METRICS_CRON_CHECK_INTERVAL_SECONDS,
    METRICS_EVENT_ERROR_MAX_PER_WINDOW,
    METRICS_WINDOW_SECONDS,
)
from .reporter import report_metrics_batch
from .local_buffer import MetricsLocalBuffer
from .crash_guard import install_guard_once, register_collector, unregister_collector

logger = logging.getLogger(__name__)

# 业务标识：随每条上报指标一起携带，供 ai-server 按产品区分
RUNTIME = "hermes"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _avg(nums: List[float]) -> Optional[float]:
    """数值列表的整数平均值，空列表返回 None（避免上报无意义的 0）。"""
    if not nums:
        return None
    return round(sum(nums) / len(nums))


def _within_last_24h(iso_ts: str, now: datetime) -> bool:
    """判断 ISO8601 时间字符串是否落在 [now-24h, now] 内；解析失败视为不在窗口内。"""
    try:
        parsed = datetime.fromisoformat(iso_ts)
    except (TypeError, ValueError):
        return False
    if parsed.tzinfo is None and now.tzinfo is not None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return timedelta(0) <= now - parsed <= timedelta(hours=24)


def _count_overdue_cron_jobs() -> int:
    """复用 hermes-agent 框架自身的 overdue 判定（含 grace 窗口），避免自行猜测口径。"""
    try:
        from agent.monitoring.cron_health import build_cron_health_snapshot

        snapshot = build_cron_health_snapshot()
        for metric in snapshot.metrics:
            if metric.name == "hermes.cron.jobs.overdue":
                return int(metric.value)
    except Exception as exc:  # noqa: BLE001 — 框架内部读取失败不能影响主流程
        logger.debug("[metrics] cron overdue 读取失败: %s", exc)
    return 0


def resolve_hermes_home() -> str:
    """与 adapter.py/history.py 等处一致的 HERMES_HOME 解析规则。"""
    return os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


class _ConnectionWindowState:
    """60s 窗口内累计的连接质量状态，flush 时打包为 metric.connection 并部分清零。"""

    __slots__ = (
        "connected", "ws_duration_ms", "ticket_success", "ticket_duration_ms",
        "half_open_detected", "reconnect_attempts", "event_error_count",
    )

    def __init__(self) -> None:
        self.connected: bool = False
        self.ws_duration_ms: Optional[float] = None
        self.ticket_success: Optional[bool] = None
        self.ticket_duration_ms: Optional[float] = None
        self.half_open_detected: int = 0
        self.reconnect_attempts: int = 0
        # 本窗口内已上报的event.error 计数，用于 record_event_error() 限流
        # （见 config.METRICS_EVENT_ERROR_MAX_PER_WINDOW），随窗口 flush 重置。
        self.event_error_count: int = 0


class MetricsCollector:
    """
    :param instance_id: 云服务器实例本地标识（本地兜底用途，ai-server侧最终以鉴权身份为准）
    :param api_base_url: 当前 site 的 API base url
    :param get_sessions: 返回 ``{uin: _PerUinSession}`` 的回调（每次调用取最新快照）
    :param get_aiohttp_session: 返回复用的 ``aiohttp.ClientSession``
    :param get_consent_agreed: 返回当前是否已同意日志/指标采集（``bool``）的回调。
        授权粒度是整机（instance）级——本地授权文件（见 consent.py）由前端
        通过 TAT 写入，一台实例上所有 uin 共用同一份文件，因此这里是单个
        全局布尔值，不区分 uin。该值只在 adapter.py 建立连接时同步读取一次
        并缓存，本collector 不主动发起读取、不做实时撤回感知（撤回在下次
        重连时生效）。
    """

    def __init__(
        self,
        *,
        instance_id: str,
        api_base_url: str,
        get_sessions: Callable[[], Dict[str, object]],
        get_aiohttp_session: Callable[[], object],
        get_consent_agreed: Callable[[], bool],
    ) -> None:
        self._instance_id = instance_id
        self._api_base_url = api_base_url
        self._get_sessions = get_sessions
        self._get_aiohttp_session = get_aiohttp_session
        self._get_consent_agreed = get_consent_agreed

        self._conn_windows: Dict[str, _ConnectionWindowState] = {}
        self._buffers: Dict[str, MetricsLocalBuffer] = {}
        self._buffer_dir = os.path.join(resolve_hermes_home(), "metrics")

        self._window_task: Optional[asyncio.Task] = None
        self._cron_task: Optional[asyncio.Task] = None
        self._stopped = False

    def _is_consented(self) -> bool:
        """是否已同意日志/指标采集（整机级），未同意（含未决策）一律返回 False。"""
        return bool(self._get_consent_agreed())

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stopped = False
        self._window_task = asyncio.create_task(self._window_loop())
        self._cron_task = asyncio.create_task(self._cron_loop())
        install_guard_once()
        register_collector(self)

    async def stop(self) -> None:
        self._stopped = True
        for task in (self._window_task, self._cron_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._window_task = None
        self._cron_task = None
        unregister_collector(self)

    # ------------------------------------------------------------------
    # 连接质量事件（由 adapter.py 在 _on_session_connected/_disconnected 中调用）
    # ------------------------------------------------------------------

    def record_connect_success(self, uin: str, ws_duration_ms: Optional[float]) -> None:
        if not self._is_consented():
            return
        window = self._get_window(uin)
        window.connected = True
        window.ws_duration_ms = ws_duration_ms

    def record_disconnect(self, uin: str) -> None:
        if not self._is_consented():
            return
        window = self._get_window(uin)
        window.connected = False

    def _get_window(self, uin: str) -> _ConnectionWindowState:
        if uin not in self._conn_windows:
            self._conn_windows[uin] = _ConnectionWindowState()
        return self._conn_windows[uin]

    # ------------------------------------------------------------------
    # 事件型：错误事件（发生即立即上报，不进入 60s 聚合窗口）
    # ------------------------------------------------------------------

    def record_event_error(self, uin: str, api_key: str, module: str, **details) -> None:
        if not self._is_consented():
            return

        # 限流：event.error 是"发生即立即上报"，每次调用都会create_task 发起
        # 一次独立 HTTP 请求（带重试）。若上游出现错误风暴（网络抽风导致大量
        # inbound/outbound 失败），不限流会无上限创建任务、对 ai-server 造成
        # 突发流量压力。这里复用已有的 60s 聚合窗口做计数与重置，超过阈值后
        # 静默丢弃多余条目（不进降级缓冲，避免风暴期间缓冲文件被打爆）。
        window = self._get_window(uin)
        if window.event_error_count >= METRICS_EVENT_ERROR_MAX_PER_WINDOW:
            return
        window.event_error_count += 1

        item = {
            "type": "event.error",
            "instance_id": self._instance_id,
            "runtime": RUNTIME,
            # uin：与 §3.7 payload schema 一致（TS collector.ts 亦携带），供跨层按 uin 关联。
            "uin": uin,
            "timestamp": _now_iso(),
            "module": module,
            **details,
        }
        asyncio.create_task(self._send_or_buffer(uin, api_key, [item], is_event=True))

    # ------------------------------------------------------------------
    # 供 crash_guard 调用
    # ------------------------------------------------------------------

    def build_crash_report_targets(self) -> List[Tuple[str, str, str]]:
        """返回 [(api_base_url, api_key, instance_id), ...]，逐个已授权 uin 上报崩溃事件。

        遍历的是 ``get_sessions()`` 返回的活字典（非快照），理论上若崩溃瞬间
        恰好有并发写入会抛 ``RuntimeError: dictionary changed size during
        iteration``。这里不做防御性拷贝——调用方 ``crash_guard._report_crash_to_all``
        已经用 try/except 包住本方法的调用（异常时continue 到下一个
        collector），因此该竞态最坏情况只是丢失这一次崩溃上报，不会影响
        ``sys.excepthook`` 委托给原 hook 的既定退出流程。
        """
        targets = []
        if not self._is_consented():
            return targets
        for uin, sess in self._get_sessions().items():
            api_key = getattr(sess, "api_key", "")
            if api_key:
                targets.append((self._api_base_url, api_key, self._instance_id))
        return targets

    # ------------------------------------------------------------------
    # 内部：60s 窗口 flush
    # ------------------------------------------------------------------

    async def _window_loop(self) -> None:
        while not self._stopped:
            try:
                await asyncio.sleep(METRICS_WINDOW_SECONDS)
                if self._stopped:
                    return
                await self._flush_window()
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 — 窗口循环不能被单次异常打断
                logger.warning("[metrics] window flush failed: %s", exc)

    async def _flush_window(self) -> None:
        if not self._is_consented():
            return

        sessions = dict(self._get_sessions())
        window_start_ts = _now_iso()
        ts = _now_iso()

        for uin, sess in sessions.items():
            api_key = getattr(sess, "api_key", "")
            if not api_key:
                continue

            window = self._get_window(uin)

            # 从 session 侧拉取并重置累计计数（ticket 结果/半开检测/重连次数）
            snapshot_fn = getattr(sess, "get_metrics_snapshot", None)
            snapshot = snapshot_fn() if callable(snapshot_fn) else {}
            ticket_success = snapshot.get("ticket_success", window.ticket_success)
            ticket_duration_ms = snapshot.get("ticket_duration_ms", window.ticket_duration_ms)
            half_open_detected = snapshot.get("half_open_count", 0) or 0
            reconnect_attempts = snapshot.get("reconnect_attempts", 0) or 0
            # ws_duration_ms 是"最近一次连接耗时"状态量，snapshot 里若有则优先
            ws_duration_ms = snapshot.get("ws_duration_ms", window.ws_duration_ms)

            connection_item = {
                "type": "metric.connection",
                "instance_id": self._instance_id,
                "runtime": RUNTIME,
                "uin": uin,
                "window_start_ts": window_start_ts,
                "timestamp": ts,
                "connected": window.connected,
                "ws_duration_ms": ws_duration_ms,
                "ticket_success": ticket_success,
                "ticket_duration_ms": ticket_duration_ms,
                "half_open_detected": half_open_detected,
                "reconnect_attempts": reconnect_attempts,
            }

            reliable = getattr(sess, "reliable", None)
            stats = reliable.get_stats() if reliable is not None else {}
            total_emitted = stats.get("total_emitted")
            total_confirmed = stats.get("total_confirmed")
            flush_success_rate = (
                round(total_confirmed / total_emitted, 2)
                if total_emitted else None
            )

            messaging_item = {
                "type": "metric.messaging",
                "instance_id": self._instance_id,
                "runtime": RUNTIME,
                "uin": uin,
                "window_start_ts": window_start_ts,
                "timestamp": ts,
                "total_emitted": total_emitted,
                "total_confirmed": total_confirmed,
                "total_retried": stats.get("total_retried"),
                "total_failed": stats.get("total_failed"),
                "pending_count": stats.get("current_pending"),
                "flush_success_rate": flush_success_rate,
            }

            # 窗口切换：connected 是状态量不复位，其余累计量已从 session 侧清零读取
            self._conn_windows[uin] = _ConnectionWindowState()
            self._conn_windows[uin].connected = window.connected

            await self._send_or_buffer(uin, api_key, [connection_item, messaging_item], is_event=False)
            await self._try_flush_buffered_gap(uin, api_key)

    # ------------------------------------------------------------------
    # 内部：cron 定时任务健康检测
    # ------------------------------------------------------------------

    async def _cron_loop(self) -> None:
        while not self._stopped:
            try:
                await asyncio.sleep(METRICS_CRON_CHECK_INTERVAL_SECONDS)
                if self._stopped:
                    return
                await self._check_cron_health()
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("[metrics] cron health check skipped: %s", exc)

    async def _check_cron_health(self) -> None:
        """cron 定时任务健康检测。

        数据来源：hermes-agent 框架自身的 cron 子系统（``cron.jobs.list_jobs()`` +
        ``agent.monitoring.cron_health.build_cron_health_snapshot()``）。
        hermes-lightclaw 作为 ``kind: platform`` 插件，由 hermes-agent 的 gateway
        进程在同一 Python 解释器/venv 内加载运行，因此可以直接 import 这些框架
        内部模块读取真实的 job 存储（``~/.hermes/cron/jobs.json``），不需要另建
        存储或猜测格式。若脱离 hermes-agent 宿主运行（如独立单测），import 会
        失败，此时静默跳过——不伪造数据。

        cron 健康数据是进程级（一个 profile 一份 jobs.json），非 uin 级——挑选
        任一当前已授权（已同意采集、持有 api_key）的 uin 挂载上报，字段口径
        对齐 TS collector.ts 的 checkCronHealth()：
        - ``skipped_last_24h`` 固定为 0：hermes 的 ``mark_job_run()`` 只产出
          ok/error 两态，没有 OpenClaw cron store 的“并发跳过”概念；
        - ``missing_last_24h``：复用框架自身 ``hermes.cron.jobs.overdue``
          指标（已启用且逾期超过 grace 窗口未运行的任务数），而非自行猜测
          overdue 判定逻辑，避免与框架口径产生偏差。
        """
        if not self._is_consented():
            return

        try:
            from cron.jobs import list_jobs
        except ImportError:
            return

        # cron 数据与 uin 无关，选任一已授权（有 api_key）的 uin 挂载上报
        target = self._pick_authorized_uin()
        if target is None:
            return
        uin, api_key = target

        try:
            jobs = list_jobs(include_disabled=True)
        except Exception as exc:  # noqa: BLE001 — 框架内部读取失败不能影响主流程
            logger.debug("[metrics] cron jobs 读取失败: %s", exc)
            return

        now = self._hermes_now()
        window_start_ts = _now_iso()
        ts = _now_iso()

        succeeded = 0
        failed = 0
        detail_items: List[Dict] = []

        for job in jobs:
            last_run_at = job.get("last_run_at")
            last_status = job.get("last_status")
            if last_run_at and _within_last_24h(last_run_at, now):
                if last_status == "ok":
                    succeeded += 1
                elif last_status == "error":
                    failed += 1

            detail_items.append({
                "type": "metric.cron.detail",
                "instance_id": self._instance_id,
                "runtime": RUNTIME,
                "uin": uin,
                "window_start_ts": window_start_ts,
                "timestamp": ts,
                "job_id": job.get("id", ""),
                "name": job.get("name"),
                "enabled": bool(job.get("enabled", True)),
                "last_run_at": last_run_at,
                "last_run_status": last_status,
                "next_run_at": job.get("next_run_at"),
            })

        summary_item = {
            "type": "metric.cron",
            "instance_id": self._instance_id,
            "runtime": RUNTIME,
            "uin": uin,
            "window_start_ts": window_start_ts,
            "timestamp": ts,
            "total_enabled": sum(1 for job in jobs if job.get("enabled", True)),
            "succeeded_last_24h": succeeded,
            "failed_last_24h": failed,
            "skipped_last_24h": 0,
            "missing_last_24h": _count_overdue_cron_jobs(),
        }

        await self._send_or_buffer(uin, api_key, [summary_item, *detail_items], is_event=False)

    def _pick_authorized_uin(self) -> Optional[Tuple[str, str]]:
        """挑选任一当前持有 api_key（即已鉴权、可上报）的 uin，用于挂载进程级指标。"""
        for uin, sess in dict(self._get_sessions()).items():
            api_key = getattr(sess, "api_key", "")
            if api_key:
                return uin, api_key
        return None

    @staticmethod
    def _hermes_now() -> datetime:
        try:
            from hermes_time import now as hermes_now
            return hermes_now()
        except ImportError:
            return datetime.now().astimezone()

    # ------------------------------------------------------------------
    # 内部：发送或降级缓冲
    # ------------------------------------------------------------------

    def _get_buffer(self, uin: str) -> MetricsLocalBuffer:
        if uin not in self._buffers:
            self._buffers[uin] = MetricsLocalBuffer(
                self._buffer_dir, f"{self._instance_id}-{uin}", METRICS_BUFFER_FILE_MAX_BYTES,
            )
        return self._buffers[uin]

    async def _send_or_buffer(
        self, uin: str, api_key: str, items: List[Dict], *, is_event: bool,
    ) -> None:
        if not items:
            return

        chunks = [
            items[i:i + METRICS_BATCH_MAX_ITEMS]
            for i in range(0, len(items), METRICS_BATCH_MAX_ITEMS)
        ]

        aiohttp_session = self._get_aiohttp_session()
        buffer = self._get_buffer(uin)

        for chunk in chunks:
            ok = await report_metrics_batch(self._api_base_url, aiohttp_session, chunk, api_key)
            if not ok:
                for item in chunk:
                    if is_event or item.get("type") == "event.error":
                        buffer.buffer_event(item)
                    else:
                        buffer.merge_aggregated(item)

    async def _try_flush_buffered_gap(self, uin: str, api_key: str) -> None:
        """每个窗口 flush 后尝试补报此前故障期缓冲的数据；成功才清空，避免二次丢失。"""
        buffer = self._get_buffer(uin)
        if not buffer.has_pending():
            return
        items = buffer.build_flush_items(self._instance_id)
        if not items:
            return

        aiohttp_session = self._get_aiohttp_session()
        ok = await report_metrics_batch(self._api_base_url, aiohttp_session, items, api_key)
        if ok:
            buffer.clear()

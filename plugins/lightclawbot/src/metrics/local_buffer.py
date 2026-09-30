"""
LightClaw (hermes) — 指标本地降级缓冲（对应 §3.5 的 L2/L3/L4）。

    L2 停止重试，转入内存队列缓冲
    L3 长时间不可用：聚合型指标窗口合并（不新开窗口，累加进当前大窗口）、
       事件型错误限流去重（同类仅保留代表性样本 + 计数），并落盘兜底
    L4 恢复后：一次性 flush 合并摘要（metric.gap_summary），而非逐条重放

每个 uin 一个实例，故障隔离到 uin 级别（与 per_uin_session 一致）。
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 每个错误 module 最多保留的代表性样本数，超出仅计数不再存明细
_MAX_EVENT_SAMPLES_PER_MODULE = 5


class MetricsLocalBuffer:
    """单个 uin 的本地降级缓冲。构造时尝试从磁盘恢复上次未 flush 完的缓冲。"""

    def __init__(self, buffer_dir: str, key: str, max_file_bytes: int):
        self._file_path = os.path.join(buffer_dir, f"buffer-{key}.json")
        self._max_file_bytes = max_file_bytes
        self._gap_window: Optional[Dict] = None
        self._event_samples: Dict[str, List[Dict]] = {}
        self._event_counts: Dict[str, int] = {}
        self._load_from_disk()

    def has_pending(self) -> bool:
        return self._gap_window is not None or bool(self._event_counts)

    def merge_aggregated(self, item: Dict) -> None:
        """故障期收到聚合型指标：累加进当前未上报的大窗口，不新开窗口。

        按 item["type"] 分组累加（``merged`` 为 ``{type: {field: value}}``），
        避免不同指标类型（如 metric.connection 和 metric.messaging）恰好出现
        同名数值字段时被错误地混合累加到一起。
        """
        if self._gap_window is None:
            self._gap_window = {
                "gap_start_ts": item.get("window_start_ts") or item.get("timestamp"),
                "merged": {},
                "dropped_event_count": 0,
            }
        item_type = str(item.get("type") or "unknown")
        bucket = self._gap_window["merged"].setdefault(item_type, {})
        for key, value in item.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                bucket[key] = bucket.get(key, 0) + value
        self._persist()

    def buffer_event(self, item: Dict) -> None:
        """故障期收到事件型指标：按module 限流去重，仅保留前N 条代表性样本 + 总计数。"""
        module_key = str(item.get("module") or "unknown")
        self._event_counts[module_key] = self._event_counts.get(module_key, 0) + 1

        samples = self._event_samples.setdefault(module_key, [])
        if len(samples) < _MAX_EVENT_SAMPLES_PER_MODULE:
            samples.append(item)
        elif self._gap_window is not None:
            self._gap_window["dropped_event_count"] += 1
        self._persist()

    def build_flush_items(self, instance_id: str) -> List[Dict]:
        """构建恢复后一次性补报的条目列表。"""
        items: List[Dict] = []
        now_iso = _now_iso()

        if self._gap_window is not None:
            items.append({
                "type": "metric.gap_summary",
                "instance_id": instance_id,
                "timestamp": now_iso,
                "gap_start_ts": self._gap_window["gap_start_ts"],
                "gap_end_ts": now_iso,
                "merged_metrics": self._gap_window["merged"],
                "dropped_event_count": self._gap_window["dropped_event_count"],
            })

        for module_key, samples in self._event_samples.items():
            total_count = self._event_counts.get(module_key, len(samples))
            for sample in samples:
                original_message = str(sample.get("message") or "")
                items.append({
                    **sample,
                    "message": (
                        f"{original_message} (故障期内module={module_key} "
                        f"共 {total_count} 次，此为代表性样本)"
                    ),
                })

        return items

    def clear(self) -> None:
        self._gap_window = None
        self._event_samples = {}
        self._event_counts = {}
        self._persist()

    # ---- 本地文件持久化（原子写入：tmp + rename）----

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
            payload = {
                "gap_window": self._gap_window,
                "event_counts": self._event_counts,
                "event_samples": self._event_samples,
            }
            data = json.dumps(payload, ensure_ascii=False)

            # 文件大小上限保护：超过则丢弃事件明细样本，仅保留计数——
            # 宁可损失细节，也要保留"曾经发生过丢失"这个信号本身。
            if len(data.encode("utf-8")) > self._max_file_bytes:
                self._event_samples = {}
                payload = {
                    "gap_window": self._gap_window,
                    "event_counts": self._event_counts,
                    "event_samples": {},
                }
                data = json.dumps(payload, ensure_ascii=False)

            tmp_path = f"{self._file_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp_path, self._file_path)
        except Exception as exc:
            logger.warning("[metrics] persist local buffer failed: %s", exc)

    def _load_from_disk(self) -> None:
        try:
            if not os.path.exists(self._file_path):
                return
            with open(self._file_path, "r", encoding="utf-8") as f:
                raw = f.read()
            if not raw.strip():
                return
            parsed = json.loads(raw)
            self._gap_window = parsed.get("gap_window")
            self._event_counts = parsed.get("event_counts") or {}
            self._event_samples = parsed.get("event_samples") or {}
        except Exception as exc:
            logger.warning("[metrics] load local buffer failed: %s", exc)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

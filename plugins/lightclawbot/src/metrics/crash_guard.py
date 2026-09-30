"""
hermes LightClaw — 指标崩溃兜底（Crash Guard）

对应 §2.4「插件进程异常」+ §3.4「传输方式」的崩溃前 last-gasp 上报场景。

本插件以 Hermes entry point 加载，与宿主共享同一进程。
``sys.excepthook`` 天然安全——我们只在"此前已存在的 excepthook"之前插入一次
顺路上报，finally 中始终委托给它，**绝不改变进程最终的崩溃/退出行为**
（与 Node ``process.on('uncaughtException')`` 不同，后者会默默阻止退出）。
asyncio 任务内未捕获异常不会走到这里（仅被事件循环记录），故不 hook
``loop.set_exception_handler``，避免过度扩大"崩溃"定义、引入框架级改动。
"""

import logging
import sys
import traceback
import urllib.error
import urllib.request
from typing import Protocol

from ..config import API_PATH_METRICS_REPORT

logger = logging.getLogger(__name__)

# 业务标识：本插件运行时，固定为 hermes，随崩溃上报条目一起携带，供 ai-server 按产品区分
RUNTIME = "hermes"

_installed = False
_original_excepthook = None
_active_collectors: "set" = set()


class CrashReportable(Protocol):
    """MetricsCollector 需要实现的最小接口，避免 crash_guard 反向依赖 collector.py。"""

    def build_crash_report_targets(self):
        """返回 [(api_base_url, api_key, instance_id), ...] 列表，用于崩溃时逐个上报。"""
        ...


def register_collector(collector: "CrashReportable") -> None:
    """MetricsCollector 构造时调用，将自身注册进崩溃兜底名单。"""
    _active_collectors.add(collector)
    install_guard_once()


def unregister_collector(collector: "CrashReportable") -> None:
    """MetricsCollector stop() 时调用。"""
    _active_collectors.discard(collector)


def _report_crash_sync(api_base_url: str, api_key: str, instance_id: str, message: str, stack: str) -> None:
    """同步、阻塞、短超时地上报一条崩溃事件。

    进程即将退出，不能用 asyncio（事件循环状态在崩溃时不可靠），
    改用标准库 ``urllib.request`` 做一次最多等待2s 的 best-effort POST。
    失败即放弃，不重试（进程都要退出了，没有"下次"）。
    """
    import json as _json

    body = _json.dumps({
            "items": [{
                "type": "event.error",
                "instance_id": instance_id,
                "runtime": RUNTIME,
                "timestamp": _now_iso(),
                "module": "process",
                "message": message,
                "stack": stack,
            }],
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{api_base_url}{API_PATH_METRICS_REPORT}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Product": "channel",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=2.0)
    except (urllib.error.URLError, OSError, ValueError):
        pass


def _now_iso() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _report_crash_to_all(message: str, stack: str) -> None:
    for collector in list(_active_collectors):
        try:
            targets = collector.build_crash_report_targets()
        except Exception:
            continue
        for api_base_url, api_key, instance_id in targets:
            try:
                _report_crash_sync(api_base_url, api_key, instance_id, message, stack)
            except Exception:
                # 崩溃处理路径本身绝不能再抛异常
                pass


def _crash_excepthook(exc_type, exc_value, exc_tb) -> None:
    try:
        message = str(exc_value)
        stack = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error("[metrics] uncaught exception: %s", message)
        _report_crash_to_all(message, stack)
    except Exception:
        pass
    finally:
        # 始终委托给此前已存在的 excepthook（默认sys.__excepthook__ 或宿主自定义钩子），
        # 保证我们绝不改变进程最终的崩溃/退出行为。
        if _original_excepthook is not None:
            _original_excepthook(exc_type, exc_value, exc_tb)


def install_guard_once() -> None:
    global _installed, _original_excepthook
    if _installed:
        return
    _installed = True
    _original_excepthook = sys.excepthook
    sys.excepthook = _crash_excepthook

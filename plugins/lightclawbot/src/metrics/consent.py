"""
LightClaw (hermes) — 实例日志/指标采集用户授权

用户在前端点击同意/不同意后，经 TAT 直接写入实例文件。
插件仅需在连接建立时同步读取一次本地文件决定是否采集。
撤回授权要等到下次重新连接才会重新读取生效。

授权粒度：实例级别——一台实例上所有 uin 共用同一份文件，开关全局唯一。
"""

import json
import logging
import os

from .collector import resolve_hermes_home

logger = logging.getLogger(__name__)

_VALID_STATUSES = {"pending", "agreed", "rejected"}


def resolve_metrics_consent_file_path() -> str:
    """授权文件路径：$HERMES_HOME/identity/collect-log-auth.json（默认 ~/.hermes/identity/...）"""
    return os.path.join(resolve_hermes_home(), "identity", "collect-log-auth.json")


def read_metrics_consent() -> str:
    """同步读取本地授权文件。

    文件不存在、内容非法、读取异常统一 fail-safe closed，返回 ``'pending'``
    （查不到就当作未同意，不采集）。
    """
    file_path = resolve_metrics_consent_file_path()
    try:
        if not os.path.exists(file_path):
            return "pending"
        with open(file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        status = data.get("status") if isinstance(data, dict) else None
        if status in _VALID_STATUSES:
            return status
        return "pending"
    except Exception as exc:
        logger.warning("[metrics] read_metrics_consent failed: %s", exc)
        return "pending"

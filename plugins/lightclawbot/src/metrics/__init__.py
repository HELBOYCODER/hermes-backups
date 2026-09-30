"""
LightClaw (hermes) — 指标模块统一出口
"""

from .collector import MetricsCollector
from .reporter import report_metrics_batch
from .local_buffer import MetricsLocalBuffer
from .crash_guard import install_guard_once, register_collector, unregister_collector
from .consent import read_metrics_consent, resolve_metrics_consent_file_path

__all__ = [
    "MetricsCollector",
    "report_metrics_batch",
    "MetricsLocalBuffer",
    "install_guard_once",
    "register_collector",
    "unregister_collector",
    "read_metrics_consent",
    "resolve_metrics_consent_file_path",
]

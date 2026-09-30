"""为消息处理建立短生命周期身份上下文，不保存凭据或共享环境变量。"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from ..config import CHANNEL_KEY
from ..tenancy import resolve_connector_api_key


@dataclass
class _CallerScope:
    """共享有效标记使复制到后台任务的上下文在消息结束后同步失效。"""

    user_id: str
    active: bool = True


@dataclass(frozen=True)
class ConnectorCaller:
    """只供内部调用使用，凭据不参与对象的日志表示。"""

    user_id: str
    api_key: str = field(repr=False)


class ConnectorIdentityError(Exception):
    """用固定原因报告身份失败，不暴露账户或凭据内容。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_caller_scope: ContextVar[_CallerScope | None] = ContextVar("lightclaw_connector_caller", default=None)


@contextmanager
def connector_message_scope(event):
    """只从本渠道私聊事件来源获取用户，离开消息处理后撤销身份。"""
    source = getattr(event, "source", None)
    platform = getattr(source, "platform", None)
    platform = getattr(platform, "value", platform)
    user_id = getattr(source, "user_id", None)
    valid = (platform == CHANNEL_KEY and getattr(source, "chat_type", None) == "dm"
             and isinstance(user_id, str) and user_id.isascii() and user_id.isdecimal())
    scope = _CallerScope(user_id) if valid else None
    # 无效或匿名嵌套消息也要遮蔽外层身份，不能继承前一位用户。
    token = _caller_scope.set(scope)
    try:
        yield
    finally:
        if scope is not None:
            scope.active = False
        _caller_scope.reset(token)


def resolve_connector_caller() -> ConnectorCaller:
    """在使用时查询最新映射；普通执行器不传播上下文时明确拒绝推断身份。"""
    scope = _caller_scope.get()
    if scope is None or not scope.active:
        raise ConnectorIdentityError("identity_missing")
    api_key = resolve_connector_api_key(scope.user_id)
    if api_key is None:
        raise ConnectorIdentityError("account_unavailable")
    return ConnectorCaller(scope.user_id, api_key)

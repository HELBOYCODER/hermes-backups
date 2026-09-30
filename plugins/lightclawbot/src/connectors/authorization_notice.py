"""为真实工具拒绝绑定消息路由，在消息事件循环发送固定错误步骤。"""

import asyncio
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from ..config import CHANNEL_KEY

_inbound = ContextVar('connector_notice_inbound', default=None)
_notice = ContextVar('connector_notice_active', default=None)
_CODES = frozenset({
    'CONNECTOR_IDENTITY_INVALID', 'CONNECTOR_RUNTIME_CONTEXT_INVALID',
    'CONNECTOR_CONFIG_INVALID', 'CONNECTOR_CONFIG_MISMATCH',
    'CONNECTOR_MANAGED_STATE_INVALID', 'CONNECTOR_MIGRATION_PENDING',
    'CONNECTOR_OWNERSHIP_MISSING', 'CONNECTOR_OWNERSHIP_INVALID',
    'CONNECTOR_OWNERSHIP_KEY_UNAVAILABLE', 'CONNECTOR_OWNERSHIP_MISMATCH',
    'CONNECTOR_OWNERSHIP_PENDING', 'CONNECTOR_EXECUTION_SOURCE_MISMATCH',
})


@dataclass
class NoticeScope:
    """本轮发送能力独立于按用户保存的可变回复状态。"""

    loop: object
    send: object
    route: dict
    active: bool = True


@contextmanager
def inbound_notice_scope(data):
    """入站任务独立保存路由；后台处理继承快照，入站返回不提前撤销。"""
    token = _inbound.set({'user': data.get('from'), 'original': data.get('msgId')})
    try:
        yield
    finally:
        _inbound.reset(token)


def record_notice_source(user_id, chat_id, agent_id):
    """仅在既有入站校验完成、实际构造会话来源时记录规范化路由。"""
    state = _inbound.get()
    if state is not None and state['user'] == user_id:
        state.update(chat=chat_id, agent=agent_id)


def record_notice_reply(user_id, reply_id):
    """捕获实际发出的本轮回复编号，不在调用失败时查询最近一轮。"""
    state = _inbound.get()
    if state is not None and state['user'] == user_id:
        state.setdefault('reply', reply_id)


@contextmanager
def authorization_notice_scope(event, adapter):
    """实际消息处理期间启用通知，结束或取消后撤销线程复制的能力。"""
    state = _inbound.get()
    source = getattr(event, 'source', None)
    platform = getattr(source, 'platform', None)
    platform = getattr(platform, 'value', platform)
    user = getattr(source, 'user_id', None)
    scope = None
    if (state and all(key in state for key in ('chat', 'agent', 'reply'))
            and platform == CHANNEL_KEY and getattr(source, 'chat_type', None) == 'dm'
            and isinstance(user, str) and user.isascii() and user.isdecimal()
            and user == state['user'] and getattr(event, 'message_id', None) == state['original']):
        scope = NoticeScope(asyncio.get_running_loop(), adapter._fire_and_forget, {
            'from': adapter._bot_client_id, 'to': user, 'msgId': state['reply'],
            'replyToMsgId': state['original'], 'agentId': state['agent'],
            'extra': {'chatId': state['chat']},
        })
    token = _notice.set(scope)
    try:
        yield
    finally:
        if scope is not None:
            scope.active = False
        _notice.reset(token)


def notify_authorization_failure(code):
    """每个实际拒绝出口发送一次；目录过滤及普通执行错误不触发提示。"""
    scope = _notice.get()
    if scope is None or not scope.active or code not in _CODES:
        return

    def send():
        """排队后再查有效标记，禁止消息结束后的迟到通知。"""
        if not scope.active:
            return
        timestamp = int(time.time() * 1000)
        step = {'stepId': f'connector-auth-{uuid.uuid4()}', 'seq': timestamp,
                'type': 'tool', 'status': 'error',
                'text': '连接器调用失败，请检查身份和连接器配置', 'connectorError': {'code': code}}
        frame = {**scope.route, 'timestamp': timestamp, 'kind': 'thinking_step', 'content': '',
                 'extra': {**scope.route['extra'], 'step': step}}
        try:
            scope.send('message:private', frame)
        except Exception:
            pass  # 通知失败不能改变原始鉴权拒绝结果。

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    try:
        if current_loop is scope.loop:
            send()
        else:
            scope.loop.call_soon_threadsafe(send)
    except RuntimeError:
        pass  # 事件循环已关闭时保留原始拒绝，不创建新的发送线程。

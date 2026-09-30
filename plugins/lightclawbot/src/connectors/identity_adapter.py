"""在现有消息处理边界绑定身份，保留原有适配器的单实例及业务流程。"""

import asyncio

from ..adapter import LightClawAdapter
from .caller_identity import connector_message_scope
from .authorization_notice import (authorization_notice_scope, inbound_notice_scope,
    record_notice_source, record_notice_reply)


class ConnectorIdentityAdapter(LightClawAdapter):
    """仅增加消息身份生命周期，不替换核心工具分发或共享 MCP 连接。"""

    def set_message_handler(self, handler):
        """包装实际处理回调，避免入站派发返回时提前撤销后台任务身份。"""
        if handler is None:
            return super().set_message_handler(handler)

        async def handle_with_identity(event):
            # 在后台实际处理消息时绑定；正常结束、异常和取消都会撤销身份。
            with connector_message_scope(event), authorization_notice_scope(event, self):
                from .owned_tool_registration import owned_message_scope
                async with owned_message_scope():
                    return await handler(event)

        return super().set_message_handler(handle_with_identity)

    async def _handle_incoming_message(self, data):
        """为每个入站任务建立快照容器，不依赖按用户保存的最近消息。"""
        with inbound_notice_scope(data):
            return await super()._handle_incoming_message(data)

    def _build_session_source(self, user_id, chat_id='', agent_id='main'):
        """复用原有校验后的会话路由，不重新解释客户端字段。"""
        source = super()._build_session_source(user_id, chat_id, agent_id=agent_id)
        record_notice_source(user_id, chat_id, agent_id)
        return source

    def _get_or_create_round_id(self, chat_id):
        """记录原发送链路实际选择的回复编号。"""
        reply_id = super()._get_or_create_round_id(chat_id)
        record_notice_reply(chat_id, reply_id)
        return reply_id

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        """重连前恢复受管 MCP 运行状态，并兼容宿主传入的重连标记。"""
        from .owned_execution import start_owned_mcp
        start_owned_mcp()
        return await super().connect(is_reconnect=is_reconnect)

    async def disconnect(self):
        """先关闭受管调用通道，再执行原适配器断开；清理不阻塞消息事件循环。"""
        from .owned_execution import close_owned_mcp
        try:
            await asyncio.to_thread(close_owned_mcp)
        finally:
            await super().disconnect()

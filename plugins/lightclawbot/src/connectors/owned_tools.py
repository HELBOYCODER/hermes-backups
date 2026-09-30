"""在消息作用域内提供独立工具目录，处理函数本身执行归属校验。"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .caller_identity import resolve_connector_caller, ConnectorIdentityError
from .managed_store import read_managed_store
from .mcp_execution import failure as tool_failure
from .authorization_notice import notify_authorization_failure
from .mcp_session import McpSessionError
from .owned_catalog import OwnedCatalogDiscovery, MAX_TOOLS, MAX_SCHEMA_BYTES
from .owned_execution import current_owned_mcp

logger = logging.getLogger(__name__)
SLOTS = tuple(f'lightclaw_mcp_{index:03d}' for index in range(1, MAX_TOOLS + 1))
_turn = ContextVar('lightclaw_owned_tool_turn', default=None)


def _is_revoked_ownership_code(code):
    """只有归属快照失效才触发运行态清理，避免身份冲突误伤其他会话。"""
    return code in {'CONNECTOR_OWNERSHIP_MISSING', 'CONNECTOR_OWNERSHIP_PENDING', 'CONNECTOR_OWNERSHIP_INVALID'}


def _invalidate_if_revoked(executor, server_name, result):
    """在最终授权校验失败时释放被撤销连接，清理异常不能覆盖原始错误码。"""
    if isinstance(result, dict) and not result.get('ok') and _is_revoked_ownership_code(result.get('code')):
        invalidate = getattr(executor, 'invalidate', None)
        if callable(invalidate):
            invalidate(server_name)


def _diagnostic_code(error):
    """只保留固定错误码或异常类型，避免日志泄漏地址和凭据。"""
    if isinstance(error, (ConnectorIdentityError, McpSessionError)):
        value = str(error)
        if value and value.replace('_', '').isalnum() and len(value) <= 64:
            return value
    return type(error).__name__


def failure(code):
    """实际调用拒绝时附加通知，保留既有工具错误协议。"""
    notify_authorization_failure(code)
    return tool_failure(code)


@dataclass
class _Turn:
    """复制到后台线程的上下文共享撤销标记，消息结束后全部失效。"""

    owner: object
    executor: object = None
    discovery: object = None
    entries: dict = field(default_factory=dict, repr=False)
    published: set = field(default_factory=set)
    active: bool = True


class OwnedTools:
    """共享注册入口只读取当前消息上下文，不保存进程级当前用户。"""

    def __init__(self, executor_getter=current_owned_mcp):
        """运行时通过读取器获取，适配器重连后不继续使用旧执行器。"""
        self.executor_getter = executor_getter
        self.closed = False

    @asynccontextmanager
    async def message_scope(self):
        """异步准备当前用户的目录，异常只撤销本次 MCP 能力，不中断普通对话。"""
        turn = _Turn(self)
        token = _turn.set(turn)
        try:
            try:
                resolve_connector_caller()
                if not self.closed:
                    turn.executor = self.executor_getter()
                    if turn.executor is not None and not turn.executor.closed:
                        turn.discovery = OwnedCatalogDiscovery(turn.executor.runtime, turn.executor.bridge)
                        await asyncio.to_thread(self._prepare, turn)
            except Exception as exc:
                logger.warning('[lightclaw] 连接器目录准备失败: code=%s', _diagnostic_code(exc))
                turn.entries.clear()
            yield
        finally:
            turn.active = False
            turn.published.clear()
            if turn.discovery is not None:
                turn.discovery.close()
            _turn.reset(token)

    def _prepare(self, turn):
        """只发现显式插件来源，单次消息总目录有界并完整发布。"""
        runtime = turn.executor.runtime
        marker = read_managed_store(runtime['runtime'], runtime['configPath'], runtime.get('stateDir'))
        if marker['status'] == 'invalid':
            raise McpSessionError('CONNECTOR_MANAGED_STATE_INVALID')
        names = sorted(name for name, source in marker.get('executionSources', {}).items() if source == 'plugin')
        if len(names) > MAX_TOOLS:
            raise McpSessionError('CONNECTOR_TOOL_CATALOG_LIMIT')
        logger.info('[lightclaw] 连接器目录开始发现: plugin_servers=%d', len(names))
        entries, size = {}, 0
        for name in names:
            if self.closed or not turn.active:
                return
            try:
                catalog = turn.discovery.discover(name)
            except McpSessionError as exc:
                # 他人安装或当前不可用的安装不进入当前用户目录。
                if _is_revoked_ownership_code(str(exc)):
                    invalidate = getattr(turn.executor, 'invalidate', None)
                    if callable(invalidate):
                        invalidate(name)
                logger.warning('[lightclaw] 连接器目录发现跳过: server=%s code=%s', name, _diagnostic_code(exc))
                continue
            size += len(catalog.schemas_json.encode('utf-8'))
            if size > MAX_SCHEMA_BYTES:
                raise McpSessionError('CONNECTOR_TOOL_CATALOG_LIMIT')
            for schema in catalog.schemas():
                if len(entries) >= MAX_TOOLS:
                    raise McpSessionError('CONNECTOR_TOOL_CATALOG_LIMIT')
                entries[SLOTS[len(entries)]] = (catalog, schema)
        if turn.active and not self.closed:
            turn.entries = entries
            logger.info('[lightclaw] 连接器目录发现完成: plugin_servers=%d entries=%d', len(names), len(entries))

    def current(self):
        """每次读取确认运行对象与消息均有效，拒绝其他注册代或撤销上下文。"""
        turn = _turn.get()
        if (self.closed or turn is None or turn.owner is not self or not turn.active
                or turn.executor is None or turn.executor.closed):
            return None
        resolve_connector_caller()
        if self.executor_getter() is not turn.executor:
            return None
        return turn

    def execute(self, slot, arguments):
        """验签与审批位于最终处理函数内，任何失败均返回错误而不回退原生调用。"""
        try:
            turn = self.current()
            if turn is None or slot not in turn.published or slot not in turn.entries:
                logger.warning(
                    '[lightclaw] 连接器槽位不可用: slot=%s context=%s entry=%s published=%s',
                    slot if slot in SLOTS else '<invalid>',
                    turn is not None,
                    turn is not None and slot in turn.entries,
                    turn is not None and slot in turn.published,
                )
                return failure('CONNECTOR_TOOL_UNAVAILABLE')
            catalog, schema = turn.entries[slot]

            def authorize():
                """桥接排队后再次验证同一消息和配置绑定。"""
                if self.current() is not turn or slot not in turn.published:
                    return {'ok': False, 'code': 'CONNECTOR_TOOL_UNAVAILABLE'}
                result = turn.discovery.authorize(catalog.server_name, catalog.binding)
                _invalidate_if_revoked(turn.executor, catalog.server_name, result)
                if result['ok'] and result['source'] != 'plugin':
                    return {'ok': False, 'code': 'CONNECTOR_EXECUTION_SOURCE_MISMATCH'}
                return result

            checked = authorize()
            if not checked['ok']:
                return failure(checked['code'])
            if not isinstance(arguments, dict):
                return failure('CONNECTOR_TOOL_ARGUMENTS_INVALID')
            # 桥接排队期间模型参数不能被共享引用修改；参数不参与目标或身份选择。
            arguments = json.loads(json.dumps(arguments, allow_nan=False))
            result = turn.executor.bridge.call_tool(authorize, schema['name'], arguments)
            return json.dumps(result, ensure_ascii=False)
        except ConnectorIdentityError:
            return failure('CONNECTOR_IDENTITY_INVALID')
        except McpSessionError as exc:
            return failure(str(exc))
        except Exception:
            return failure('CONNECTOR_CALL_FAILED')

    def close(self):
        """注册代关闭后所有旧处理函数和在途授权回调立即失效。"""
        self.closed = True

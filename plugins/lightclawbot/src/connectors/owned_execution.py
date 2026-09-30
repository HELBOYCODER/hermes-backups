"""接管有归属快照的原生 MCP 调用；受管分支拒绝后不进入旧处理函数。"""

import json
import threading
from .mcp_bridge import McpBridge
from .mcp_runtime import resolve_mcp_target, check_mcp_policy
from .mcp_session import McpSessionError
from .mcp_transport import ConnectorCallError
from .ownership_guard import guard_ownership
from .managed_store import read_managed_store
from .ownership_store import read_ownership_snapshot
from .ownership_runtime import ownership_runtime, actual_ownership_servers


class OwnedMcpExecutor:
    """用精确原生工具映射查找目标，证明验证决定归属及官方或自定义类型。"""

    def __init__(self, runtime, bridge=None, read_servers=actual_ownership_servers):
        """记录本进程已识别的受管安装，证明后续消失时禁止兼容回退。"""
        self.runtime, self.bridge, self.read_servers = runtime, bridge or McpBridge(), read_servers
        self.managed, self.closed = set(), False
        self._lock = threading.Lock()

    def execute(self, tool_name, args):
        """返回 None 仅代表未迁移配置，其他失败必须交给上层转为固定错误载荷。"""
        target = resolve_mcp_target(tool_name, owned=True)
        if target is None:
            return None
        runtime, name = self.runtime, target.server_name
        if self.closed:
            raise McpSessionError('CONNECTOR_RUNTIME_CLOSED')
        with self._lock:
            marker = read_managed_store(runtime['runtime'], runtime['configPath'], runtime.get('stateDir'))
            if marker['status'] == 'invalid':
                raise McpSessionError('CONNECTOR_MANAGED_STATE_INVALID')
            if marker['status'] == 'ready' and name in marker['servers']:
                self.managed.add(name)
            stored = read_ownership_snapshot(runtime['runtime'], runtime['configPath'], name, runtime.get('stateDir'))
            if stored['status'] != 'ready' and name in self.managed:
                self.invalidate(name)
            if stored['status'] == 'missing' and name not in self.managed:
                return None
            self.managed.add(name)
        expected = None

        def authorize():
            """在桥接后的真实调用任务中重新读取身份、快照和磁盘配置。"""
            if self.closed:
                return {'ok': False, 'code': 'CONNECTOR_RUNTIME_CLOSED'}
            try:
                marker = read_managed_store(runtime['runtime'], runtime['configPath'], runtime.get('stateDir'))
                if marker['status'] == 'invalid':
                    return {'ok': False, 'code': 'CONNECTOR_MANAGED_STATE_INVALID'}
                source = marker.get('executionSources', {}).get(name, 'native')
                if source == 'pending':
                    return {'ok': False, 'code': 'CONNECTOR_MIGRATION_PENDING'}
                # 原生入口不得继续执行已经迁移到插件的安装。
                if source != 'native':
                    return {'ok': False, 'code': 'CONNECTOR_EXECUTION_SOURCE_MISMATCH'}
                result = guard_ownership(runtime, name, self.read_servers(runtime).get(name))
                if result['ok'] and expected is not None and tuple(result['target'][k] for k in fields) != expected:
                    return {'ok': False, 'code': 'CONNECTOR_CONFIG_MISMATCH'}
                return result
            except Exception:
                return {'ok': False, 'code': 'CONNECTOR_CONFIG_INVALID'}

        fields = ('userId', 'product', 'declaredInstanceId', 'installId', 'serverName', 'connectorType', 'configDigest')
        checked = authorize()
        if not checked['ok']:
            raise McpSessionError(checked['code'])
        expected = tuple(checked['target'][k] for k in fields)
        if check_mcp_policy(target):
            raise McpSessionError('CONNECTOR_POLICY_DENIED')
        result = self.bridge.call_tool(authorize, target.tool_name, args)
        # 保留 MCP 的 isError 与结构化内容，不能把协议错误改写为成功。
        return json.dumps(result, ensure_ascii=False)

    def invalidate(self, server_name):
        """撤销指定 runtime key 的运行态会话，但保留 managed 记录防止回退原生调用。"""
        if not self.closed:
            try:
                self.bridge.close_servers({server_name})
            except Exception:
                # 运行态释放是尽力清理，归属校验失败不能被清理异常覆盖。
                pass

    def close(self):
        """先使排队授权失效，再关闭会话池和桥接线程。"""
        self.closed = True
        self.bridge.close()


_active = None
_invalid = False


def current_owned_mcp():
    """独立工具与旧中间件共享当前执行器，不将配置错误视为未启用。"""
    if _invalid:
        raise McpSessionError('CONNECTOR_RUNTIME_CONTEXT_INVALID')
    return _active


def start_owned_mcp():
    """插件首次使用或重连时读取部署配置；配置错误不能静默退回旧调用。"""
    global _active, _invalid
    if _active is not None and not _active.closed:
        return
    try:
        runtime = ownership_runtime()
        # 默认配置也建立执行器；受管状态仍从原配置命名空间读取，不能降级原生。
        _active = OwnedMcpExecutor(runtime)
        _invalid = False
    except Exception:
        _invalid = True


def execute_owned_mcp(tool_name, args):
    """仅检查 MCP 工具；普通工具不受部署配置错误影响。"""
    if not isinstance(tool_name, str) or not tool_name.startswith('mcp_'):
        return None
    if _invalid:
        raise ConnectorCallError('CONNECTOR_RUNTIME_CONTEXT_INVALID')
    try:
        return _active.execute(tool_name, args) if _active is not None else None
    except McpSessionError as exc:
        raise ConnectorCallError(str(exc)) from None


def close_owned_mcp():
    """适配器断开时保留已关闭对象，避免旧调用突然进入兼容分支。"""
    if _active is not None:
        _active.close()

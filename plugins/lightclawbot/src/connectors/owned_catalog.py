"""通过插件会话发现工具，目录绑定发现时的用户、安装及配置来源。"""

import json
from dataclasses import dataclass, field

from .mcp_bridge import McpBridge
from .mcp_session import McpSessionError
from .ownership_guard import guard_ownership
from .ownership_runtime import actual_ownership_servers, resolve_ownership_execution

MAX_TOOLS = 256
MAX_PAGES = 8
MAX_SCHEMA_BYTES = 1024 * 1024


def _binding(result):
    """完整绑定实际授权目标；凭据仅在内存比较，不进入目录展示或日志。"""
    target = result['target']
    fields = ('userId', 'product', 'declaredInstanceId', 'installId', 'serverName',
              'connectorType', 'configDigest', 'url')
    return (result['source'], *(target[key] for key in fields), tuple(sorted(target['headers'].items())))


@dataclass(frozen=True)
class OwnedToolCatalog:
    """保存不可变目录，调用者拿到的参数定义副本不能篡改内部绑定。"""

    server_name: str
    schemas_json: str
    binding: tuple = field(repr=False)

    def schemas(self):
        """返回独立副本，后续宿主适配不得修改共享目录。"""
        return json.loads(self.schemas_json)


class OwnedCatalogDiscovery:
    """发现与执行共享桥接；不读宿主私有注册表，也不在全局保存当前用户。"""

    def __init__(self, runtime, bridge=None, read_native=actual_ownership_servers):
        """允许接入层复用已有桥接，其生命周期仍由创建方负责。"""
        self.runtime, self.bridge = runtime, bridge or McpBridge()
        self.read_native = read_native
        self._owns_bridge = bridge is None
        self.closed = False

    def authorize(self, server_name, expected=None):
        """每次发现及发送前重新验签，拒绝旧目录跨用户或跨配置使用。"""
        if self.closed:
            return {'ok': False, 'code': 'CONNECTOR_RUNTIME_CLOSED'}
        try:
            selected = resolve_ownership_execution(self.runtime, server_name, self.read_native)
            if not selected['ok']:
                return selected
            result = guard_ownership(self.runtime, server_name, selected['server'])
            if not result['ok']:
                return result
            result = {**result, 'source': selected['source']}
            if expected is not None and _binding(result) != expected:
                return {'ok': False, 'code': 'CONNECTOR_CONFIG_MISMATCH'}
            return result
        except Exception:
            return {'ok': False, 'code': 'CONNECTOR_CONFIG_INVALID'}

    def discover(self, server_name):
        """在当前消息身份下分页发现；异常及不完整目录不得作为成功结果发布。"""
        checked = self.authorize(server_name)
        if not checked['ok']:
            raise McpSessionError(checked['code'])
        expected = _binding(checked)

        def authorize():
            """桥接排队及握手之后仍重新检查当前消息作用域。"""
            return self.authorize(server_name, expected)

        cursor, cursors, names, schemas = None, set(), set(), []
        for _ in range(MAX_PAGES):
            page = self.bridge.list_tools(authorize, cursor)
            checked = authorize()
            if not checked['ok']:
                raise McpSessionError(checked['code'])
            if not isinstance(page, dict) or not isinstance(page.get('tools'), list):
                raise McpSessionError('CONNECTOR_TOOL_CATALOG_INVALID')
            for tool in page['tools']:
                if (not isinstance(tool, dict) or not isinstance(tool.get('name'), str)
                        or not tool['name'] or len(tool['name']) > 256 or tool['name'] in names
                        or not isinstance(tool.get('inputSchema'), dict)
                        or tool['inputSchema'].get('type') != 'object'
                        or not isinstance(tool.get('description', ''), str)):
                    raise McpSessionError('CONNECTOR_TOOL_CATALOG_INVALID')
                names.add(tool['name'])
                schemas.append({'name': tool['name'], 'description': tool.get('description', ''),
                                'inputSchema': tool['inputSchema']})
            if len(schemas) > MAX_TOOLS:
                raise McpSessionError('CONNECTOR_TOOL_CATALOG_LIMIT')
            encoded = json.dumps(schemas, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode('utf-8')) > MAX_SCHEMA_BYTES:
                raise McpSessionError('CONNECTOR_TOOL_CATALOG_LIMIT')
            cursor = page.get('nextCursor')
            if cursor is None:
                return OwnedToolCatalog(server_name, encoded, expected)
            if not isinstance(cursor, str) or not cursor or len(cursor) > 8192 or cursor in cursors:
                raise McpSessionError('CONNECTOR_TOOL_CATALOG_INVALID')
            cursors.add(cursor)
        raise McpSessionError('CONNECTOR_TOOL_CATALOG_LIMIT')

    def close(self):
        """撤销旧目录授权，并只关闭本对象创建的桥接。"""
        self.closed = True
        if self._owns_bridge:
            self.bridge.close()

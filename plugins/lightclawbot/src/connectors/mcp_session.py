"""按已验证目标复用 MCP 会话；不重放失败请求，不跨用户共享连接。"""

import asyncio
import hashlib
import json

try:
    from .mcp_sdk_compat import (
        McpSdk,
        create_client_session,
        create_http_client,
        create_request,
        dump_result,
        load_sdk,
        unpack_transport,
    )
except ImportError:  # 允许旧式文件加载测试继续复用真实会话池。
    from mcp_sdk_compat import (  # type: ignore[no-redef]
        McpSdk,
        create_client_session,
        create_http_client,
        create_request,
        dump_result,
        load_sdk,
        unpack_transport,
    )


class McpSessionError(Exception):
    """只向调用方传播固定错误码，不传播 URL、凭据或 SDK 原始异常。"""


class _Entry:
    """会话的资源所有者任务独立存在，确保 SDK 上下文在同一任务进入和退出。"""

    def __init__(self, key, slot, target):
        self.key, self.slot, self.server_name, self.target = key, slot, target['serverName'], target
        self.ready = asyncio.get_running_loop().create_future()
        self.stop, self.lock = asyncio.Event(), asyncio.Lock()
        self.task = None


class McpSessionPool:
    """每个插件运行实例持有一个池；关闭插件时必须调用 close。"""

    def __init__(self, timeout=30, capacity=64):
        if timeout <= 0 or capacity < 1:
            raise ValueError('MCP 会话参数无效')
        self.timeout, self.capacity = timeout, capacity
        self.entries, self.closed, self.sdk = {}, False, None

    def _sdk(self) -> McpSdk:
        """首次需要网络会话时探测 SDK，后续请求复用探测结果。"""
        if self.sdk is None:
            self.sdk = load_sdk()
        return self.sdk

    @staticmethod
    def _authorize(authorize):
        """回调必须调用归属校验层，并实时读取可信身份与当前配置。"""
        try:
            result = authorize()
            if not result['ok']:
                raise McpSessionError(result['code'])
            return {**result['target'], 'headers': dict(result['target']['headers'])}
        except McpSessionError:
            raise
        except Exception:
            raise McpSessionError('CONNECTOR_CALL_FAILED') from None

    @staticmethod
    def _keys(target):
        """作用域固定到用户和安装；摘要及实际凭据参与连接版本，但不保留明文缓存键。"""
        slot = json.dumps([target[k] for k in ('userId', 'product', 'declaredInstanceId', 'installId', 'serverName', 'connectorType')], separators=(',', ':'))
        version = json.dumps([slot, target['configDigest'], target['url'], sorted(target['headers'].items())], ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha256(version.encode()).hexdigest(), slot

    async def _lifetime(self, entry):
        """只进行首次握手并持有传输，业务请求由带身份的原调用任务发送。"""
        try:
            sdk = self._sdk()
            async with create_http_client(sdk, entry.target['headers'], self.timeout) as http:
                async with sdk.transport(entry.target['url'], http_client=http) as streams:
                    read, write, _ = unpack_transport(streams)
                    async with create_client_session(sdk, read, write, self.timeout) as client:
                        async with asyncio.timeout(self.timeout):
                            await client.initialize()
                        entry.ready.set_result(client)
                        await entry.stop.wait()
        except BaseException:
            if not entry.ready.done():
                entry.ready.set_exception(McpSessionError('CONNECTOR_CALL_FAILED'))
        finally:
            if self.entries.get(entry.key) is entry:
                self.entries.pop(entry.key, None)

    async def _retire(self, entry):
        """从缓存删除后关闭资源，旧握手不能重新进入池。"""
        if self.entries.get(entry.key) is entry:
            self.entries.pop(entry.key, None)
        entry.stop.set()
        if entry.task:
            try:
                await asyncio.wait_for(asyncio.shield(entry.task), self.timeout)
            except asyncio.TimeoutError:
                entry.task.cancel()
                await asyncio.gather(entry.task, return_exceptions=True)

    async def _request(self, authorize, method, params):
        """在等待握手及串行锁之后再次授权；失败只结束本次请求，不自动重试。"""
        target = self._authorize(authorize)
        key, slot = self._keys(target)
        if self.closed:
            raise McpSessionError('CONNECTOR_SESSION_CLOSED')
        for old in list(self.entries.values()):
            if old.slot == slot and old.key != key:
                await self._retire(old)
        # 关闭旧连接期间身份或凭据也可能改变，不能继续使用第一次校验的结果。
        if self._keys(self._authorize(authorize))[0] != key:
            raise McpSessionError('CONNECTOR_CONFIG_MISMATCH')
        if self.closed:
            raise McpSessionError('CONNECTOR_SESSION_CLOSED')
        entry = self.entries.get(key)
        if entry is None:
            if len(self.entries) >= self.capacity:
                raise McpSessionError('CONNECTOR_SESSION_LIMIT')
            entry = _Entry(key, slot, target)
            self.entries[key] = entry
            entry.task = asyncio.create_task(self._lifetime(entry))
        try:
            client = await asyncio.shield(entry.ready)
            async with entry.lock:
                if self.closed or self.entries.get(key) is not entry or entry.stop.is_set():
                    raise McpSessionError('CONNECTOR_SESSION_CLOSED')
                if self._keys(self._authorize(authorize))[0] != key:
                    raise McpSessionError('CONNECTOR_CONFIG_MISMATCH')
                # 使用 SDK 的请求与结果类型，避免高级接口隐式补发工具发现请求。
                request, result_type = create_request(self._sdk(), method, params)
                result = await client.send_request(request, result_type)
                return dump_result(result)
        except BaseException as exc:
            await self._retire(entry)
            if isinstance(exc, (McpSessionError, asyncio.CancelledError)):
                raise
            raise McpSessionError('CONNECTOR_CALL_FAILED') from None

    async def list_tools(self, authorize, cursor=None):
        """按页发现工具，保留协议游标，由调用方控制发现范围。"""
        return await self._request(authorize, 'tools/list', {} if cursor is None else {'cursor': cursor})

    async def call_tool(self, authorize, name, arguments):
        """发送一次工具调用，保留 MCP 的 isError 和内容，不重放业务请求。"""
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            raise McpSessionError('CONNECTOR_CONFIG_INVALID')
        return await self._request(authorize, 'tools/call', {'name': name, 'arguments': arguments})

    async def close_servers(self, server_names):
        """只关闭指定 runtime key 的会话，不影响其他用户或连接器。"""
        targets = set(server_names)
        await asyncio.gather(*(self._retire(entry) for entry in list(self.entries.values())
                               if entry.server_name in targets))

    async def close(self):
        """禁止新请求并关闭全部连接；插件退出时由生命周期入口调用。"""
        self.closed = True
        await asyncio.gather(*(self._retire(entry) for entry in list(self.entries.values())))

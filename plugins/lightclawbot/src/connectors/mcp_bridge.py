"""为同步宿主中间件提供持久异步执行循环，保留调用任务的身份上下文。"""

import asyncio
import concurrent.futures
import contextvars
import threading
from .mcp_session import McpSessionError, McpSessionPool


class McpBridge:
    """所有会话资源归属同一个后台循环；同步调用只等待结果，不创建临时循环。"""

    def __init__(self, pool_factory=McpSessionPool, timeout=65):
        """延迟创建线程，避免未使用 MCP 时占用运行资源。"""
        self._factory, self._timeout = pool_factory, timeout
        self._lock = threading.Lock()
        self._loop = self._thread = self._pool = None
        self._closed = False

    def _start(self):
        """在锁内创建唯一循环，资源创建由该循环执行。"""
        if self._closed:
            raise McpSessionError('CONNECTOR_RUNTIME_CLOSED')
        if self._loop is not None:
            return
        ready = threading.Event()
        self._loop = asyncio.new_event_loop()

        def run():
            """线程退出前清理未完成任务，防止残留连接继续发送。"""
            asyncio.set_event_loop(self._loop)
            ready.set()
            try:
                self._loop.run_forever()
            finally:
                tasks = asyncio.all_tasks(self._loop)
                for task in tasks:
                    task.cancel()
                self._loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.close()

        self._thread = threading.Thread(target=run, name='lightclaw-mcp', daemon=True)
        self._thread.start()
        ready.wait()

    def call_tool(self, authorize, name, arguments):
        """在同一持久会话上执行工具，不自动重放失败请求。"""
        return self._execute('call_tool', authorize, name, arguments)

    def list_tools(self, authorize, cursor=None):
        """工具发现复用执行会话及调用者上下文，分页不重复建立连接。"""
        return self._execute('list_tools', authorize, cursor)

    def close_servers(self, server_names):
        """在 MCP 后台循环中释放指定 runtime key，不为未建立会话启动后台线程。"""
        targets = set(server_names)
        with self._lock:
            if self._closed or self._loop is None or self._pool is None:
                return
            if threading.current_thread() is self._thread:
                asyncio.create_task(self._pool.close_servers(targets))
                return
            future = asyncio.run_coroutine_threadsafe(self._pool.close_servers(targets), self._loop)
        try:
            future.result(timeout=self._timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()

    def _execute(self, operation, *arguments):
        """显式复制同步调用者上下文，后台排队后仍由真实身份校验函数读取。"""
        context = contextvars.copy_context()
        with self._lock:
            self._start()
            if threading.current_thread() is self._thread:
                raise McpSessionError('CONNECTOR_RUNTIME_UNSUPPORTED')

            async def execute():
                """池在唯一循环内创建，所有用户共享池对象但不共享用户连接。"""
                if self._closed:
                    raise McpSessionError('CONNECTOR_RUNTIME_CLOSED')
                if self._pool is None:
                    self._pool = self._factory()
                return await getattr(self._pool, operation)(*arguments)

            future = context.run(asyncio.run_coroutine_threadsafe, execute(), self._loop)
        try:
            return future.result(timeout=self._timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise McpSessionError('CONNECTOR_CALL_TIMEOUT') from None

    def close(self):
        """停止接收新调用并在原循环关闭会话，最后等待线程退出。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop, thread = self._loop, self._thread
        if loop is None:
            return

        async def shutdown():
            """会话 SDK 上下文必须在所属循环退出。"""
            if self._pool is not None:
                await self._pool.close()

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), loop).result(timeout=self._timeout)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=self._timeout)

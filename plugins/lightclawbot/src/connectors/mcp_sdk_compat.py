"""兼容 MCP 1.x 与 2.x 的导入、传输和结果模型。"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from importlib import metadata
import inspect
import re
from datetime import timedelta
from typing import Any


class McpSdkError(RuntimeError):
    """MCP SDK 不可用或接口形状不受支持。"""


@dataclass(frozen=True)
class McpSdk:
    """保存一次探测得到的 SDK 入口，后续调用复用同一组对象。"""

    version: str
    major: int
    client_session: Any
    types: Any
    transport: Any
    httpx: Any


def parse_mcp_major(version: str) -> int:
    """解析 MCP 主版本，只接受当前适配的 1.x 和 2.x。"""
    match = re.match(r"^\s*(\d+)(?:\.|$)", str(version))
    if not match:
        raise McpSdkError("MCP SDK 版本无法识别")
    major = int(match.group(1))
    if major not in (1, 2):
        raise McpSdkError("MCP SDK 主版本不受支持")
    return major


def _version() -> str:
    """从 distribution 元数据读取版本，缺少元数据时回退到模块属性。"""
    try:
        return metadata.version("mcp")
    except metadata.PackageNotFoundError:
        try:
            return str(getattr(importlib.import_module("mcp"), "__version__"))
        except Exception as exc:
            raise McpSdkError("MCP SDK 未安装") from exc


def select_transport() -> Any:
    """优先使用新 transport 名称，兼容旧版弃用别名。"""
    try:
        module = importlib.import_module("mcp.client.streamable_http")
    except Exception as exc:
        raise McpSdkError("MCP Streamable HTTP transport 不可用") from exc
    for name in ("streamable_http_client", "streamablehttp_client"):
        factory = getattr(module, name, None)
        if callable(factory):
            return factory
    raise McpSdkError("MCP Streamable HTTP transport 入口不可用")


def select_httpx(transport_module: Any, major: int) -> Any:
    """优先复用 SDK transport 已导入的 HTTP 模块，避免跨模块混用类型。"""
    del major  # 模块自身的依赖比版本号更可信，保留参数便于调用方表达版本。
    for name in ("httpx2", "httpx"):
        value = getattr(transport_module, name, None)
        if value is not None and hasattr(value, "AsyncClient"):
            return value
    for name in ("httpx2", "httpx"):
        try:
            value = importlib.import_module(name)
        except ImportError:
            continue
        if hasattr(value, "AsyncClient"):
            return value
    raise McpSdkError("MCP HTTP 客户端不可用")


def load_sdk() -> McpSdk:
    """一次性加载 SDK 入口，调用方应缓存返回值避免每次反射导入。"""
    version = _version()
    major = parse_mcp_major(version)
    try:
        client_session = getattr(importlib.import_module("mcp"), "ClientSession")
        types = importlib.import_module("mcp.types")
        transport_module = importlib.import_module("mcp.client.streamable_http")
    except (ImportError, AttributeError) as exc:
        raise McpSdkError("MCP SDK 接口不完整") from exc
    transport = select_transport()
    return McpSdk(version, major, client_session, types,
                  transport, select_httpx(transport_module, major))


def unpack_transport(streams: Any) -> tuple[Any, Any, Any]:
    """把 MCP 1.x 三元组和 2.x 二元组统一为三元组。"""
    if not isinstance(streams, (tuple, list)) or len(streams) not in (2, 3):
        raise McpSdkError("MCP transport 返回值不受支持")
    return streams[0], streams[1], streams[2] if len(streams) == 3 else None


def create_http_client(sdk: McpSdk, headers: dict[str, str], timeout: float) -> Any:
    """使用 MCP SDK 实际依赖的 HTTP 模块创建客户端。"""
    return sdk.httpx.AsyncClient(headers=dict(headers), timeout=timeout,
                                 follow_redirects=False, trust_env=False)


def create_client_session(sdk: McpSdk, read: Any, write: Any, timeout: float) -> Any:
    """按 ClientSession 签名传递可选超时，兼容旧版和新版 SDK。"""
    kwargs: dict[str, Any] = {}
    try:
        params = inspect.signature(sdk.client_session).parameters
    except (TypeError, ValueError):
        params = {}
    if "read_timeout_seconds" in params:
        kwargs["read_timeout_seconds"] = (
            float(timeout) if sdk.major >= 2 else timedelta(seconds=timeout)
        )
    return sdk.client_session(read, write, **kwargs)


def create_request(sdk: McpSdk, method: str, params: dict[str, Any]) -> tuple[Any, Any]:
    """构造 1.x/2.x 都支持的原始请求和结果类型。"""
    types = sdk.types
    try:
        if method == "tools/list":
            request = types.ListToolsRequest(
                params=types.PaginatedRequestParams(**params))
            result_type = types.ListToolsResult
        elif method == "tools/call":
            request = types.CallToolRequest(
                params=types.CallToolRequestParams(**params))
            result_type = types.CallToolResult
        else:
            raise McpSdkError("MCP 请求方法不受支持")
        wrapper = getattr(types, "ClientRequest", None)
        if sdk.major == 1 and callable(wrapper):
            try:
                request = wrapper(request)
            except TypeError:
                # 部分 MCP 1.x 构建也直接接受具体请求类。
                pass
        return request, result_type
    except (AttributeError, TypeError) as exc:
        raise McpSdkError("MCP 请求类型不受支持") from exc


def dump_result(result: Any) -> dict[str, Any]:
    """把 Pydantic 结果或旧版字典模型统一序列化为字典。"""
    if isinstance(result, dict):
        return result
    if callable(getattr(result, "model_dump", None)):
        return result.model_dump(by_alias=True, exclude_none=True)
    if callable(getattr(result, "dict", None)):
        return result.dict(by_alias=True, exclude_none=True)
    raise McpSdkError("MCP 结果类型不受支持")

"""内置连接器的独立请求传输，不修改共享连接或自动重放工具调用。"""

import http.client
import json
import re
import uuid
from urllib.parse import urlsplit

from ..config import resolve_site_urls

MAX_RESPONSE_BYTES = 1024 * 1024
ERROR_CODES = {"CONNECTOR_IDENTITY_INVALID", "CONNECTOR_ACCESS_DENIED", "CONNECTOR_CONFIG_INVALID",
               "CONNECTOR_AUTH_INVALID", "CONNECTOR_CALL_FAILED"}


class ConnectorCallError(Exception):
    """只传播固定错误码，不把请求凭据或原始响应写入日志。"""

    def __init__(self, code="CONNECTOR_CALL_FAILED"):
        super().__init__(code)
        self.code = code


def strict_url(server_name, config):
    """校验本站地址和安装键，重新构造严格路由以丢弃任意附加参数。"""
    if not isinstance(config, dict) or config.get("enabled") is False or config.get("command"):
        raise ConnectorCallError("CONNECTOR_CONFIG_INVALID")
    for key in ("type", "transport"):
        if key in config and config[key] not in ("http", "streamable-http"):
            raise ConnectorCallError("CONNECTOR_CONFIG_INVALID")
    raw = config.get("url")
    if not isinstance(raw, str) or any(c.isspace() for c in raw) or config.get("baseUrl") is not None:
        raise ConnectorCallError("CONNECTOR_CONFIG_INVALID")
    try:
        url = urlsplit(raw)
        origin = urlsplit(resolve_site_urls()["api"])
        match = re.fullmatch(r"/connectors/mcp/(?:caller-v1/)?i/([A-Za-z0-9_-]{8,128})", url.path)
        if (not match or url.scheme != "https" or url.netloc != origin.netloc
                or url.username or url.password or url.query or url.fragment):
            raise ConnectorCallError("CONNECTOR_CONFIG_INVALID")
        install_id = match[1]
        if not server_name.endswith("-" + install_id[:8]):
            raise ConnectorCallError("CONNECTOR_CONFIG_INVALID")
        return f"https://{origin.netloc}/connectors/mcp/caller-v1/i/{install_id}"
    except (ValueError, TypeError):
        raise ConnectorCallError("CONNECTOR_CONFIG_INVALID") from None


def call_strict_mcp(url, caller, tool_name, args):
    """直接发送无状态工具请求；不跟随重定向、不重试，响应大小有上限。"""
    if not caller.api_key or re.search(r"[\s,]", caller.api_key) or not isinstance(args, dict):
        raise ConnectorCallError("CONNECTOR_IDENTITY_INVALID")
    target = urlsplit(url)
    # 传输层再次限制目标，不能由工具参数绕过地址构造器。
    if (target.scheme != "https" or target.netloc != urlsplit(resolve_site_urls()["api"]).netloc
            or target.query or target.fragment or not re.fullmatch(
                r"/connectors/mcp/caller-v1/i/[A-Za-z0-9_-]{8,128}", target.path)):
        raise ConnectorCallError("CONNECTOR_CONFIG_INVALID")
    request_id = uuid.uuid4().hex
    body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                       "params": {"name": tool_name, "arguments": args}}, ensure_ascii=False).encode("utf-8")
    connection = http.client.HTTPSConnection(target.hostname, timeout=30)
    try:
        connection.request("POST", target.path, body, {"Authorization": f"Bearer {caller.api_key}",
            "Content-Type": "application/json", "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise ConnectorCallError()
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ConnectorCallError()
        value = json.loads(payload)
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0" or value.get("id") != request_id:
            raise ConnectorCallError()
        if "error" in value:
            error = value["error"]
            data = error.get("data") if isinstance(error, dict) else None
            code = data.get("code") if isinstance(data, dict) else None
            raise ConnectorCallError(code if isinstance(code, str) and code in ERROR_CODES else "CONNECTOR_CALL_FAILED")
        result = value.get("result")
        if not isinstance(result, dict) or result.get("isError") is True or not isinstance(result.get("content"), list):
            raise ConnectorCallError()
        # 目前平台内置 MCP 仅返回文本；不把未知富媒体当成正常结果。
        content = result["content"]
        if any(not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str) for item in content):
            raise ConnectorCallError()
        output = {"result": "\n".join(item["text"] for item in content)}
        if isinstance(result.get("structuredContent"), dict):
            output["structuredContent"] = result["structuredContent"]
        return json.dumps(output, ensure_ascii=False)
    finally:
        connection.close()

"""适配已核对的 Hermes 原生工具来源和信任检查接口，缺少契约时拒绝猜测。"""

import importlib
from dataclasses import dataclass

from .mcp_transport import ConnectorCallError, strict_url


@dataclass(frozen=True)
class McpTarget:
    """从真实注册信息得到的调用目标，不携带安装者凭据。"""

    server_name: str
    tool_name: str
    url: str


def resolve_mcp_target(tool_name, *, owned=False):
    """由宿主的精确映射找服务器，再用原始工具目录确认名称和当前可见性。"""
    # 普通工具不加载 MCP 模块；未知 MCP 名称必须确认来源后才能放行。
    if not isinstance(tool_name, str) or not tool_name.startswith("mcp_"):
        return None
    core = importlib.import_module("tools.mcp_tool")
    registry = importlib.import_module("tools.registry").registry
    schema = importlib.import_module("tools.mcp_tool_schema")
    with core._lock:
        server_name = core._mcp_tool_server_names.get(tool_name)
        if not isinstance(server_name, str):
            raise ConnectorCallError("CONNECTOR_RUNTIME_UNSUPPORTED")
        if not server_name.startswith("agentchat-") or (not owned and server_name.startswith("agentchat-custom-")):
            return None
        server = core._servers.get(server_name)
        tools = list(getattr(server, "_tools", ()))
        trust_known = server_name in core._server_trust_levels
    entry = registry.get_entry(tool_name)
    if entry is None or entry.toolset != f"mcp-{server_name}" or not trust_known:
        raise ConnectorCallError("CONNECTOR_RUNTIME_UNSUPPORTED")
    candidates = [tool.name for tool in tools if schema._convert_mcp_schema(server_name, tool)["name"] == tool_name]
    if len(candidates) != 1:
        raise ConnectorCallError("CONNECTOR_RUNTIME_UNSUPPORTED")
    if owned:
        return McpTarget(server_name, candidates[0], "")
    cfg = importlib.import_module("hermes_cli.config").load_config()
    config = cfg.get("mcp_servers", {}).get(server_name) if isinstance(cfg, dict) else None
    return McpTarget(server_name, candidates[0], strict_url(server_name, config))


def check_mcp_policy(target):
    """复用原生 MCP 的信任审批及熔断检查，不因新传输跳过宿主已有保护。"""
    handlers = importlib.import_module("tools.mcp_tool_handlers")
    return (handlers._trust_gate_check(target.server_name, target.tool_name)
            or handlers._check_circuit_breaker(target.server_name))

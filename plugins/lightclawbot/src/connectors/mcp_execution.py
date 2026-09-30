"""在实际工具执行处接管内置 MCP，任何受管调用失败都不执行原 handler。"""

import importlib
import json
import logging

from .caller_identity import ConnectorIdentityError, resolve_connector_caller
from .mcp_runtime import check_mcp_policy, resolve_mcp_target
from .mcp_transport import ConnectorCallError, call_strict_mcp

logger = logging.getLogger(__name__)


def failure(code):
    """返回稳定的工具失败载荷，不泄漏底层异常或把拒绝结果标成成功。"""
    return json.dumps({"error": "连接器调用失败，请检查身份和连接器配置", "code": code}, ensure_ascii=False)


def execute_connector_mcp(*, tool_name, args, next_call, **kwargs):
    """仅确定为非受管工具时调用下一环；异常返回失败，避免宿主异常回退。"""
    try:
        # 在执行边界接管已启用的受管配置，拒绝结果不得进入旧处理函数。
        from .owned_execution import execute_owned_mcp
        owned = execute_owned_mcp(tool_name, args)
        if owned is not None:
            return owned
        target = resolve_mcp_target(tool_name)
        if target is not None:
            resolve_connector_caller()
            blocked = check_mcp_policy(target)
            if blocked:
                return failure("CONNECTOR_POLICY_DENIED")
            # 审批等待期间消息可能结束或账户映射变化，发送前重新读取身份。
            caller = resolve_connector_caller()
            return call_strict_mcp(target.url, caller, target.tool_name, args)
    except ConnectorIdentityError:
        return failure("CONNECTOR_IDENTITY_INVALID")
    except ConnectorCallError as exc:
        return failure(exc.code)
    except Exception:
        # 不能把异常交给宿主；其执行中间件异常处理可能继续调用旧 handler。
        return failure("CONNECTOR_CALL_FAILED")
    return next_call(args)


def register_connector_mcp(ctx):
    """只在宿主明确支持执行中间件时注册，旧宿主提示未启用而不伪造能力。"""
    try:
        contract = importlib.import_module("hermes_cli.middleware")
        supported = (callable(getattr(ctx, "register_middleware", None))
                     and "tool_execution" in contract.VALID_MIDDLEWARE)
    except (ImportError, AttributeError):
        supported = False
    if not supported:
        logger.warning("当前 Hermes 不支持连接器执行中间件，严格调用校验未启用，需要升级宿主。")
        return False
    from .owned_execution import start_owned_mcp
    start_owned_mcp()
    ctx.register_middleware("tool_execution", execute_connector_mcp)
    return True

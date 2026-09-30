"""注册固定工具槽，通过请求副本提供当前消息目录，不覆盖共享工具定义。"""

import importlib
import logging
from copy import deepcopy
from contextlib import asynccontextmanager

from .owned_tools import OwnedTools, SLOTS
from .owned_execution import current_owned_mcp, close_owned_mcp

logger = logging.getLogger(__name__)
_active = None
_BRIDGE_TOOLS = frozenset({'tool_search', 'tool_describe', 'tool_call'})


def _name(tool):
    """识别三种已核对的提供方工具结构，未知结构不猜测。"""
    if not isinstance(tool, dict):
        return None
    function = tool.get('function')
    return function.get('name') if isinstance(function, dict) else tool.get('name')


def _render_slot(name, catalog, schema, original):
    """按请求中已有的工具格式生成当前连接器槽位，避免改变宿主协议。"""
    function = {'name': name, 'description': f"{catalog.server_name} / {schema['name']}：{schema['description']}",
                'parameters': deepcopy(schema['inputSchema'])}
    if original.get('type') == 'function' and isinstance(original.get('function'), dict):
        return {'type': 'function', 'function': function}
    if original.get('type') == 'function' and isinstance(original.get('name'), str):
        return {'type': 'function', **function}
    if 'input_schema' in original and isinstance(original.get('name'), str):
        return {'name': name, 'description': function['description'],
                'input_schema': function['parameters']}
    return None


def shape_request(controller, *, request, **kwargs):
    """替换已允许的槽，并在 Hermes 桥接入口存在时追加当前消息目录槽位。"""
    turn = None
    try:
        turn = controller.current()
        if turn is not None:
            turn.published.clear()
        if not isinstance(request, dict) or not isinstance(request.get('tools'), list):
            return None
        result, tools, published, checked_catalogs = dict(request), [], set(), {}
        appended = 0
        for original in request['tools']:
            name = _name(original)
            if name not in SLOTS:
                tools.append(original)
                continue
            if turn is None or name not in turn.entries:
                continue
            catalog, schema = turn.entries[name]
            # 同一请求内按目录验签一次，避免每个工具重复读文件；执行时仍逐次验签。
            if catalog.server_name not in checked_catalogs:
                checked_catalogs[catalog.server_name] = turn.discovery.authorize(catalog.server_name, catalog.binding)
            checked = checked_catalogs[catalog.server_name]
            if not checked['ok'] or checked['source'] != 'plugin':
                continue
            replacement = _render_slot(name, catalog, schema, original)
            if replacement is None:
                continue
            tools.append(replacement)
            published.add(name)
        bridge_template = next((original for original in request['tools']
                                if _name(original) in _BRIDGE_TOOLS), None)
        if turn is not None and bridge_template is not None:
            for name, (catalog, schema) in turn.entries.items():
                if name in published:
                    continue
                if catalog.server_name not in checked_catalogs:
                    checked_catalogs[catalog.server_name] = turn.discovery.authorize(catalog.server_name, catalog.binding)
                checked = checked_catalogs[catalog.server_name]
                if not checked['ok'] or checked['source'] != 'plugin':
                    continue
                replacement = _render_slot(name, catalog, schema, bridge_template)
                if replacement is None:
                    continue
                tools.append(replacement)
                published.add(name)
                appended += 1
        result['tools'] = tools
        choice = request.get('tool_choice')
        if (not tools or isinstance(choice, dict) and _name(choice) in SLOTS and _name(choice) not in published):
            result.pop('tool_choice', None)
        if turn is not None:
            turn.published = published
        logger.info(
            '[lightclaw] 连接器请求发布: request_slots=%d appended_slots=%d entries=%d published=%d',
            sum(1 for original in request['tools'] if _name(original) in SLOTS),
            appended,
            len(turn.entries) if turn is not None else 0,
            len(published),
        )
        return {'request': result}
    except Exception:
        # 宿主对中间件异常会继续运行；最终处理函数仍需拒绝未发布的槽。
        if turn is not None:
            turn.published.clear()
        return None


def register_owned_tools(ctx):
    """仅在完整注册及卸载契约可用时启用，部分注册失败则撤销整个注册代。"""
    global _active
    if _active is not None:
        _active.close()
        _active = None
    controller, handles = OwnedTools(), []
    try:
        if current_owned_mcp() is None:
            return False
        contract = importlib.import_module('hermes_cli.middleware')
        if (not {'llm_request', 'tool_execution'} <= contract.VALID_MIDDLEWARE
                or any(not callable(getattr(ctx, key, None))
                       for key in ('register_tool', 'register_middleware', 'on_unload'))):
            raise ValueError()

        def stop():
            """先撤销本注册代，再关闭共享会话，旧回调不能继续发送。"""
            controller.close()
            if _active is controller:
                close_owned_mcp()

        ctx.on_unload(stop)
        def make_handler(slot):
            """闭包固定槽号，宿主额外关键字参数不能覆盖目标。"""
            def handler(arguments, **kwargs):
                """槽号由注册闭包决定，忽略宿主附带的身份与路由参数。"""
                return controller.execute(slot, arguments)
            return handler

        for slot in SLOTS:
            handle = ctx.register_tool(name=slot, toolset='lightclaw-connectors',
                schema={'name': slot, 'description': '当前消息的连接器工具入口',
                        'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': True}},
                handler=make_handler(slot), description='连接器工具', is_async=False)
            if handle is None or not callable(getattr(handle, 'dispose', None)):
                raise ValueError()
            handles.append(handle)
        ctx.register_middleware('llm_request', lambda **kwargs: shape_request(controller, **kwargs))
        if _active is not None:
            _active.close()
        _active = controller
        return True
    except Exception:
        controller.close()
        for handle in reversed(handles):
            try:
                handle.dispose()
            except Exception:
                pass
        logger.warning('当前 Hermes 未启用独立连接器工具，请检查宿主注册接口及部署配置。')
        return False


@asynccontextmanager
async def owned_message_scope():
    """无独立注册能力时保留原有对话，不能冒用上一消息目录。"""
    controller = _active
    if controller is None or controller.closed:
        yield
    else:
        async with controller.message_scope():
            yield

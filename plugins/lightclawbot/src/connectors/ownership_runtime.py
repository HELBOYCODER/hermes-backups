"""读取管理员部署的公钥配置与原始 MCP 配置，不从证明建立信任。"""

import json
import os
import pathlib
import stat
from types import MappingProxyType

from .trusted_keys import ownership_trusted_keys
from .managed_store import read_managed_store
from .ownership_store import read_plugin_execution_server


def ownership_runtime():
    """默认加载内置公钥和产品，配置变更后重新连接插件；旧开关不能关闭校验。"""
    raw = os.environ.get('LIGHTCLAW_CONNECTOR_OWNERSHIP')
    value = {} if raw is None else json.loads(raw)
    if (not isinstance(value, dict)
            or ('enabled' in value and type(value['enabled']) is not bool)
            or value.get('product', 'agentchat') not in ('agentchat', 'clawpro', 'lightvela')):
        raise ValueError('CONNECTOR_RUNTIME_CONTEXT_INVALID')
    home = pathlib.Path(os.environ.get('HERMES_HOME') or pathlib.Path.home() / '.hermes').expanduser()
    path = pathlib.Path(os.environ.get('HERMES_CONFIG') or home / 'config.yaml').expanduser().absolute()
    return MappingProxyType({'runtime': 'hermes', 'configPath': str(path), 'product': value.get('product', 'agentchat'),
                             'trustedKeys': ownership_trusted_keys(value.get('trustedKeys'))})


def actual_ownership_servers(runtime):
    """读取原始 YAML 保留占位符；文件异常时不得使用缓存或展开后的安装者凭据。"""
    import yaml
    fd = os.open(runtime['configPath'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
            raise ValueError('CONNECTOR_CONFIG_INVALID')
        raw = file.read(info.st_size + 1)
        if len(raw) != info.st_size:
            raise ValueError('CONNECTOR_CONFIG_INVALID')
    data = yaml.safe_load(raw.decode('utf-8'))
    servers = data.get('mcp_servers', {}) if isinstance(data, dict) else {}
    if not isinstance(servers, dict):
        raise ValueError('CONNECTOR_CONFIG_INVALID')
    return servers


def resolve_ownership_execution(runtime, server_name, read_native=actual_ownership_servers):
    """根据独立迁移标记选择唯一来源，迁移中或指定来源损坏均禁止回退。"""
    try:
        marker = read_managed_store(runtime['runtime'], runtime['configPath'], runtime.get('stateDir'))
        if marker['status'] == 'invalid':
            return {'ok': False, 'code': 'CONNECTOR_MANAGED_STATE_INVALID'}
        source = marker.get('executionSources', {}).get(server_name, 'native')
        if source == 'pending':
            return {'ok': False, 'code': 'CONNECTOR_MIGRATION_PENDING'}
        if source == 'plugin':
            saved = read_plugin_execution_server(runtime['runtime'], runtime['configPath'],
                                                 server_name, runtime.get('stateDir'))
            if saved['status'] != 'ready':
                return {'ok': False, 'code': 'CONNECTOR_OWNERSHIP_' + saved['status'].upper()}
            server = saved['server']
        else:
            server = read_native(runtime).get(server_name)
        if server is None:
            return {'ok': False, 'code': 'CONNECTOR_CONFIG_INVALID'}
        return {'ok': True, 'source': source, 'server': server}
    except Exception:
        return {'ok': False, 'code': 'CONNECTOR_CONFIG_INVALID'}

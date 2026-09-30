"""读取脚本保存的配置与归属证明；读取成功不代表验签通过或获得调用权限。"""

import hashlib
import json
import os
import pathlib
import re
import stat
from types import MappingProxyType

MAX_BYTES = 4 * 1024 * 1024


def read_plugin_execution_server(runtime, config_path, server_name, state_dir=None):
    """只提供插件配置来源；调用者仍须使用可信身份验签。"""
    result = read_ownership_snapshot(runtime, config_path, server_name, state_dir)
    if result['status'] != 'ready':
        return {'status': result['status']}
    return {'status': 'ready', 'server': result['snapshot']['server']}


def ownership_store_path(runtime, config_path, state_dir=None):
    """与脚本共享命名规则，实际配置路径必须由宿主接入层明确提供。"""
    if (runtime not in ('openclaw', 'hermes') or not isinstance(config_path, str)
            or not os.path.isabs(config_path) or '\0' in config_path):
        raise ValueError('连接器配置路径无效')
    config_path = '/' + os.path.abspath(config_path).lstrip('/')
    identity = runtime + '\0' + config_path
    key = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    root = pathlib.Path(state_dir) if state_dir is not None else pathlib.Path.home() / '.agentchat-connectors'
    return root / ('ownership-' + key + '.json')


def _identifier(value, limit):
    """按签名协议检查标识格式，不据此认定标识可信。"""
    return isinstance(value, str) and 0 < len(value) <= limit and re.fullmatch(r'[A-Za-z0-9_-]+', value)


def read_ownership_snapshot(runtime, config_path, server_name, state_dir=None):
    """读取有界私有文件，未完成写入或文件损坏时不返回旧证明。"""
    try:
        path = ownership_store_path(runtime, config_path, state_dir)
        if not isinstance(server_name, str) or not re.fullmatch(r'agentchat-[A-Za-z0-9_-]{1,118}', server_name):
            return {'status': 'invalid'}
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return {'status': 'missing'}
        with os.fdopen(fd, 'rb') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > MAX_BYTES:
                raise ValueError()
            raw = file.read(info.st_size + 1)
            if len(raw) != info.st_size:
                raise ValueError()
        data = json.loads(raw.decode('utf-8'))
        if (not isinstance(data, dict) or type(data.get('schemaVersion')) is not int or data['schemaVersion'] != 1
                or data.get('runtime') != runtime or data.get('configPath') != '/' + os.path.abspath(config_path).lstrip('/')
                or not isinstance(data.get('entries'), dict)):
            raise ValueError()
        if server_name not in data['entries']:
            return {'status': 'missing'}
        entry = data['entries'][server_name]
        if not isinstance(entry, dict):
            raise ValueError()
        if entry.get('state') == 'pending':
            return {'status': 'pending'}
        proof, server = entry.get('ownershipProof'), entry.get('server')
        if (entry.get('state') != 'ready' or entry.get('serverName') != server_name
                or not _identifier(entry.get('installId'), 64) or not _identifier(entry.get('instanceId'), 128)
                or entry.get('installType') not in ('builtin', 'custom')
                or not isinstance(proof, str) or len(proof) > 8192
                or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', proof)
                or not isinstance(server, dict) or set(server) != {'name', 'type', 'url', 'headers'}
                or server['name'] != server_name or server['type'] != 'http'
                or not isinstance(server['url'], str) or not server['url'].strip()
                or not isinstance(server['headers'], dict)
                or any(not isinstance(v, str) for v in server['headers'].values())):
            raise ValueError()
        # 返回独立的只读快照；接入层仍须验签，并比对可信会话及实际连接配置。
        snapshot = {key: entry[key] for key in ('state', 'installId', 'instanceId', 'installType', 'serverName', 'ownershipProof')}
        snapshot['server'] = MappingProxyType({**server, 'headers': MappingProxyType(dict(server['headers']))})
        return {'status': 'ready', 'snapshot': MappingProxyType(snapshot)}
    except Exception:
        return {'status': 'invalid'}

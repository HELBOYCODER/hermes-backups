"""读取独立持久标记；标记要求验签，不授予用户任何 MCP 权限。"""

import json
import os
import re
import stat
from types import MappingProxyType
from .ownership_store import ownership_store_path


def managed_store_path(runtime, config_path, state_dir=None):
    """与脚本及 OpenClaw 共享文件名算法，标记与证明分别存储。"""
    path = ownership_store_path(runtime, config_path, state_dir)
    return path.with_name(path.name.replace('ownership-', 'managed-', 1))


def read_managed_store(runtime, config_path, state_dir=None):
    """标记损坏与从未写入明确区分；每次读取，避免排队调用沿用旧状态。"""
    try:
        path = managed_store_path(runtime, config_path, state_dir)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return {'status': 'missing'}
        with os.fdopen(fd, 'rb') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 4 * 1024 * 1024:
                raise ValueError()
            raw = file.read(info.st_size + 1)
            if len(raw) != info.st_size:
                raise ValueError()
        data = json.loads(raw.decode('utf-8'))
        required = {'schemaVersion', 'runtime', 'configPath', 'servers'}
        if (not isinstance(data, dict) or not required <= set(data) or set(data) - required - {'executionSources'}
                or type(data['schemaVersion']) is not int or data['schemaVersion'] != 1
                or data['runtime'] != runtime or data['configPath'] != '/' + os.path.abspath(config_path).lstrip('/')
                or not isinstance(data['servers'], list) or len(data['servers']) > 16384
                or any(not isinstance(name, str) or not re.fullmatch(r'agentchat-[A-Za-z0-9_-]{1,118}', name)
                       for name in data['servers']) or len(set(data['servers'])) != len(data['servers'])):
            raise ValueError()
        sources = data.get('executionSources', {})
        if (not isinstance(sources, dict)
                or any(name not in data['servers'] or source not in ('native', 'pending', 'plugin')
                       for name, source in sources.items())):
            raise ValueError()
        return {'status': 'ready', 'servers': tuple(data['servers']),
                'executionSources': MappingProxyType(dict(sources))}
    except Exception:
        return {'status': 'invalid'}

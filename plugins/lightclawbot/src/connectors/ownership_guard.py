"""统一身份、快照、实际配置摘要及验签检查，不执行网络请求或兼容回退。"""

import hashlib
import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import urlsplit

from .caller_identity import ConnectorIdentityError, resolve_connector_caller
from .ownership_proof import verify_ownership_proof
from .ownership_store import read_ownership_snapshot

# 与 JavaScript trim 一致，避免两端对地址前后空白的处理不同。
TRIM = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def _failure(code):
    """失败不返回凭据、调用目标或原始异常。"""
    return {'ok': False, 'code': code}


def _connection(name, value, kind, install_id):
    """复制实际连接配置，按服务端固定数组和 ASCII 请求头排序计算摘要。"""
    if (not isinstance(value, Mapping) or set(value) - {'name', 'url', 'headers', 'enabled', 'type', 'transport'}
            or ('name' in value and value['name'] != name)
            or ('enabled' in value and value['enabled'] is not True)
            or any(k in value and value[k] not in ('http', 'streamable-http') for k in ('type', 'transport'))
            or not isinstance(value.get('url'), str)):
        raise ValueError()
    url = value['url'].strip(TRIM)
    parsed = urlsplit(url)
    if (not re.match(r'^https?://', url, re.I) or re.search(r'[\x00-\x20\x7f\\]|[' + TRIM + ']', url)
            or not parsed.hostname or parsed.username is not None or parsed.password is not None or '#' in url):
        raise ValueError()
    _ = parsed.port
    headers = value.get('headers')
    if headers is None:
        headers = {}
    if not isinstance(headers, Mapping):
        raise ValueError()
    headers = dict(headers)
    if kind == 'builtin':
        if (headers != {'Authorization': 'Bearer ${AGENTCHAT_API_KEY}'}
                or parsed.path != '/connectors/mcp/i/' + install_id or '?' in url):
            raise ValueError()
        canonical = ['mcp-builtin-routing-v1', name, url, 'streamable-http', True]
    else:
        names = set()
        for key, value in headers.items():
            if (not isinstance(key, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key)
                    or key.lower() in names or not isinstance(value, str)
                    or re.search(r'[\r\n\0]', value) or '${' in value):
                raise ValueError()
            names.add(key.lower())
        canonical = ['mcp-config-v1', url, [[k, headers[k]] for k in sorted(headers)], 'streamable-http', True]
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    return url, MappingProxyType(headers), digest


def guard_ownership(runtime, server_name, actual_server):
    """每次使用可信消息身份校验，运行配置不得从证明、快照或模型参数反推。"""
    try:
        if (not isinstance(runtime, Mapping) or runtime.get('product') not in ('agentchat', 'clawpro', 'lightvela')
                or not isinstance(runtime.get('trustedKeys'), Mapping)):
            return _failure('CONNECTOR_RUNTIME_CONTEXT_INVALID')
        try:
            caller = resolve_connector_caller()
        except ConnectorIdentityError:
            return _failure('CONNECTOR_IDENTITY_INVALID')
        stored = read_ownership_snapshot(runtime.get('runtime'), runtime.get('configPath'), server_name, runtime.get('stateDir'))
        if stored['status'] != 'ready':
            return _failure('CONNECTOR_OWNERSHIP_' + stored['status'].upper())
        saved = stored['snapshot']
        try:
            url, headers, digest = _connection(server_name, actual_server, saved['installType'], saved['installId'])
            _, _, previous = _connection(server_name, saved['server'], saved['installType'], saved['installId'])
        except Exception:
            return _failure('CONNECTOR_CONFIG_INVALID')
        if digest != previous:
            return _failure('CONNECTOR_CONFIG_MISMATCH')
        # 仅核对快照与签名声明，暂不验证当前运行实例的身份。
        context = {'userId': caller.user_id, 'product': runtime['product'], 'instanceId': saved['instanceId'],
                   'installId': saved['installId'], 'serverName': server_name, 'connectorType': saved['installType'],
                   'digestMode': 'mcp-builtin-routing-v1' if saved['installType'] == 'builtin' else 'mcp-config-v1',
                   'configDigest': digest}
        verified = verify_ownership_proof(saved['ownershipProof'], context, runtime['trustedKeys'])
        if not verified['ok']:
            return verified
        if saved['installType'] == 'builtin':
            # 不携带安装者凭据；原始路由验签通过后才构造服务端严格调用地址。
            if not caller.api_key or re.search(r'[^\x21-\x7e]|,', caller.api_key):
                return _failure('CONNECTOR_IDENTITY_INVALID')
            url = url.rsplit('/connectors/mcp/i/', 1)[0] + '/connectors/mcp/caller-v1/i/' + saved['installId']
            headers = MappingProxyType({'Authorization': 'Bearer ' + caller.api_key})
        target = {k: context[k] for k in ('userId', 'product', 'installId', 'serverName', 'connectorType', 'configDigest')}
        target.update(declaredInstanceId=saved['instanceId'], url=url, headers=headers)
        return {'ok': True, 'target': MappingProxyType(target)}
    except Exception:
        return _failure('CONNECTOR_CONFIG_INVALID')

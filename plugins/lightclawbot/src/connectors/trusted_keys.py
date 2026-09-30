"""随插件发布可信公钥，私钥只由 ai-server 保存。"""

from types import MappingProxyType

BUILTIN_OWNERSHIP_KEYS = MappingProxyType({
    'connector-prod-202609-v1': 'MCowBQYDK2VwAyEAtHCEMdrahyhVe6aiu6K4GWIqIXyDcH/iaYewR4vbXFs=',
})


def ownership_trusted_keys(extra=None):
    """兼容管理员配置其他密钥，禁止替换内置标识；动态更新另走签名协议。"""
    if extra is None:
        return BUILTIN_OWNERSHIP_KEYS
    if (not isinstance(extra, dict) or not extra
            or any(not isinstance(key, str) or not key
                   or (kid in BUILTIN_OWNERSHIP_KEYS and BUILTIN_OWNERSHIP_KEYS[kid] != key)
                   for kid, key in extra.items())):
        raise ValueError('CONNECTOR_RUNTIME_CONTEXT_INVALID')
    return MappingProxyType({**extra, **BUILTIN_OWNERSHIP_KEYS})

"""校验安装归属证明；可信公钥与调用身份必须由插件接入层提供。"""

import base64
import json
import re

FIELDS = {'ver', 'iss', 'aud', 'sub', 'product', 'instanceId', 'installId',
          'serverName', 'connectorType', 'digestMode', 'configDigest'}


def _failure(code):
    """仅返回固定错误码，不暴露配置、证明或密码库错误。"""
    return {'ok': False, 'code': 'CONNECTOR_OWNERSHIP_' + code}


def _decode(segment):
    """拒绝非规范 Base64URL 编码。"""
    if not re.fullmatch(r'[A-Za-z0-9_-]+', segment):
        raise ValueError()
    raw = base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))
    if base64.urlsafe_b64encode(raw).decode().rstrip('=') != segment:
        raise ValueError()
    return raw


def _object(pairs):
    """拒绝重复字段和嵌套结构，使两端对声明的理解一致。"""
    result = {}
    for key, value in pairs:
        if key in result or type(value) not in (str, int, float):
            raise ValueError()
        result[key] = value
    return result


def _parse(segment):
    """严格解析 UTF-8 平面 JSON 对象。"""
    value = json.loads(_decode(segment).decode('utf-8'), object_pairs_hook=_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(value, dict):
        raise ValueError()
    return value


def _valid(c):
    """检查固定用途、协议版本、归属字段和类型摘要配对。"""
    def identifier(value, limit):
        return isinstance(value, str) and 0 < len(value) <= limit and re.fullmatch(r'[A-Za-z0-9_-]+', value)
    return (set(c) == FIELDS and type(c['ver']) in (int, float) and c['ver'] == 1
            and c['iss'] == 'agentchat-connectors' and c['aud'] == 'agentchat-connector-runtime'
            and c['product'] in ('agentchat', 'clawpro', 'lightvela')
            and identifier(c['sub'], 64) and identifier(c['instanceId'], 128)
            and identifier(c['installId'], 64) and identifier(c['serverName'], 128)
            and c['serverName'].startswith('agentchat-') and len(c['serverName']) > 10
            and (c['connectorType'], c['digestMode']) in (
                ('custom', 'mcp-config-v1'), ('builtin', 'mcp-builtin-routing-v1'))
            and isinstance(c['configDigest'], str) and re.fullmatch(r'[a-f0-9]{64}', c['configDigest']))


def verify_ownership_proof(proof, context, trusted_keys):
    """验证可信 SPKI DER 公钥签名，再逐项匹配会话身份和实际配置，不设置有效期。"""
    if proof is None or proof == '':
        return _failure('MISSING')
    try:
        if not isinstance(proof, str) or len(proof) > 8192:
            raise ValueError()
        header_part, claims_part, signature_part = proof.split('.')
        header, claims, signature = _parse(header_part), _parse(claims_part), _decode(signature_part)
        if (set(header) != {'alg', 'typ', 'kid'} or header['alg'] != 'EdDSA'
                or header['typ'] != 'connector-ownership+jws' or not isinstance(header['kid'], str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', header['kid'])
                or not _valid(claims) or len(signature) != 64):
            raise ValueError()
        try:
            # 按需加载依赖；未接入验签的旧调用不会因密码库缺失而在导入阶段失败。
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            encoded = trusted_keys[header['kid']]
            if not isinstance(encoded, str) or len(encoded) > 4096:
                raise ValueError()
            raw = base64.b64decode(encoded, validate=True)
            if base64.b64encode(raw).decode() != encoded:
                raise ValueError()
            key = serialization.load_der_public_key(raw)
            if (not isinstance(key, Ed25519PublicKey) or key.public_bytes(
                    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != raw):
                raise ValueError()
        except Exception:
            return _failure('KEY_UNAVAILABLE')
        key.verify(signature, (header_part + '.' + claims_part).encode('ascii'))
        if not isinstance(context, dict) or any(
                claims[field] != context.get('userId' if field == 'sub' else field)
                for field in FIELDS - {'ver', 'iss', 'aud'}):
            return _failure('MISMATCH')
        return {'ok': True}
    except Exception:
        return _failure('INVALID')

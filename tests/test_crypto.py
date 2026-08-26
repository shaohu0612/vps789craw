"""
加解密与 Token 生成单元测试
"""

import time
import pytest
from crawler.crypto import (
    des_cbc_encrypt,
    des_cbc_decrypt,
    generate_auth_token,
    DEFAULT_TOKEN_KEY,
    DEFAULT_DECRYPT_KEY
)


def test_des_cbc_encrypt_decrypt_roundtrip():
    """
    测试加解密闭环一致性
    """
    original = "Hello VPS789 Cloudflare! 123456"
    encrypted_hex = des_cbc_encrypt(original, key_str=DEFAULT_DECRYPT_KEY)
    assert isinstance(encrypted_hex, str)
    assert len(encrypted_hex) > 0

    decrypted = des_cbc_decrypt(encrypted_hex, key_str=DEFAULT_DECRYPT_KEY)
    assert decrypted == original


def test_generate_auth_token():
    """
    测试鉴权 Token 生成
    """
    now_ms = 1771937123000
    token = generate_auth_token(timestamp_ms=now_ms)
    assert isinstance(token, str)
    assert len(token) > 0

    # 验证 Token 能够通过相同密钥解密还原为时间戳
    decrypted_ts = des_cbc_decrypt(token, key_str=DEFAULT_TOKEN_KEY)
    assert decrypted_ts == str(now_ms)


def test_unicode_and_json_roundtrip():
    """
    测试中文与 JSON 字符串加解密
    """
    json_text = '{"totalElements":10,"content":[{"ip":"1.1.1.1","providerUrl":"测试备注"}]}'
    encrypted = des_cbc_encrypt(json_text, key_str=DEFAULT_DECRYPT_KEY)
    decrypted = des_cbc_decrypt(encrypted, key_str=DEFAULT_DECRYPT_KEY)
    assert decrypted == json_text

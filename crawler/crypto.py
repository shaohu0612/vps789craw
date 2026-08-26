"""
加解密与 Token 签名算法模块
提供 VPS789 接口所需的 DES-CBC 加解密与动态 Token 生成。
"""

import time
import warnings
from typing import Optional

# 优先从 decrepit 导入 TripleDES 以兼容最新版 cryptography，若不存在则回退至 primitives
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
    except ImportError:
        from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, modes


# VPS789 平台约定的 DES Key（取前 8 字节）与 IV
DEFAULT_TOKEN_KEY = "385f33cb91484b04a177828829081ab7"
DEFAULT_DECRYPT_KEY = "125f33c891484b046777828569081a34"
DEFAULT_IV = b"00000000"


def des_cbc_encrypt(plain_text: str, key_str: str = DEFAULT_TOKEN_KEY, iv: bytes = DEFAULT_IV) -> str:
    """
    使用 DES-CBC 模式对明文字符串进行加密（PKCS7 填充），输出小写 Hex 字符串。

    :param plain_text: 待加密明文
    :param key_str: 密钥字符串（取前 8 字节）
    :param iv: 8 字节初始向量
    :return: 十六进制密文字符串
    """
    key_bytes = key_str[:8].encode("utf-8")
    padder = padding.PKCS7(64).padder()
    padded_data = padder.update(plain_text.encode("utf-8")) + padder.finalize()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cipher = Cipher(TripleDES(key_bytes * 3), modes.CBC(iv))
        encryptor = cipher.encryptor()
        encrypted_bytes = encryptor.update(padded_data) + encryptor.finalize()

    return encrypted_bytes.hex()


def des_cbc_decrypt(hex_cipher: str, key_str: str = DEFAULT_DECRYPT_KEY, iv: bytes = DEFAULT_IV) -> str:
    """
    使用 DES-CBC 模式对十六进制密文进行解密，输出 UTF-8 明文字符串。

    :param hex_cipher: 十六进制密文字符串
    :param key_str: 密钥字符串（取前 8 字节）
    :param iv: 8 字节初始向量
    :return: 解密后的明文字符串
    """
    key_bytes = key_str[:8].encode("utf-8")
    cipher_bytes = bytes.fromhex(hex_cipher)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cipher = Cipher(TripleDES(key_bytes * 3), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(cipher_bytes) + decryptor.finalize()

    unpadder = padding.PKCS7(64).unpadder()
    unpadded_data = unpadder.update(padded_data) + unpadder.finalize()
    return unpadded_data.decode("utf-8")


def generate_auth_token(timestamp_ms: Optional[int] = None, key_str: str = DEFAULT_TOKEN_KEY) -> str:
    """
    生成 VPS789 API 请求头所需的动态鉴权 Token。

    :param timestamp_ms: 可选毫秒时间戳，默认取当前系统时间
    :param key_str: Token 加密密钥
    :return: 加密后的 Token 字符串
    """
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    return des_cbc_encrypt(str(timestamp_ms), key_str=key_str)

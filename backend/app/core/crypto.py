"""用户 API Key 的 AES-256-GCM 加解密。

存储格式：base64( nonce(12B) + 密文 + GCM tag(16B) )。
主密钥来自环境变量 API_KEY_ENCRYPTION_KEY（64 位 hex）。任何日志与接口响应
都不得出现密文以外的 Key 内容，对外仅暴露后四位（key_last4）。
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def _master_key() -> bytes:
    raw = get_settings().api_key_encryption_key
    if raw:
        key = bytes.fromhex(raw)
        if len(key) != 32:
            raise ValueError("API_KEY_ENCRYPTION_KEY 必须是 64 位 hex 字符串（32 字节）")
        return key
    if get_settings().env == "dev":
        return hashlib.sha256(b"ielts-coach-dev-encryption-key").digest()
    raise RuntimeError("生产环境必须配置 API_KEY_ENCRYPTION_KEY")


def encrypt_secret(plaintext: str) -> str:
    nonce = os.urandom(12)
    aesgcm = AESGCM(_master_key())
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(token: str) -> str:
    data = base64.b64decode(token)
    nonce, ciphertext = data[:12], data[12:]
    aesgcm = AESGCM(_master_key())
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")

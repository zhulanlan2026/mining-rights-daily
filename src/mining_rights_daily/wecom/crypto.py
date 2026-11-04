from __future__ import annotations

import base64
import hashlib
import secrets
import struct
from hmac import compare_digest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_BLOCK = 32


class WeComCryptoError(Exception):
    """A callback signature or payload could not be verified."""


def aes_key_bytes(encoding_aes_key: str) -> bytes:
    raw = encoding_aes_key.strip()
    if len(raw) == 43:
        raw += "="
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise WeComCryptoError("EncodingAESKey 无效") from exc
    if len(decoded) != 32:
        raise WeComCryptoError("EncodingAESKey 无效")
    return decoded


def sign(token: str, timestamp: str, nonce: str, encrypt: str | None = None) -> str:
    parts = [token, timestamp, nonce]
    if encrypt is not None:
        parts.append(encrypt)
    raw = "".join(sorted(parts)).encode()
    return hashlib.sha1(raw).hexdigest()


def signatures_match(expected: str, actual: str) -> bool:
    return compare_digest(expected.encode(), actual.encode())


def encrypt(encoding_aes_key: str, text: str, receive_id: str) -> str:
    key = aes_key_bytes(encoding_aes_key)
    payload = text.encode()
    plain = secrets.token_bytes(16) + struct.pack(">I", len(payload)) + payload + receive_id.encode()
    padded = _pad(plain)
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode()


def decrypt(encoding_aes_key: str, encrypted: str, receive_id: str) -> str:
    key = aes_key_bytes(encoding_aes_key)
    try:
        raw = base64.b64decode(encrypted)
    except Exception as exc:
        raise WeComCryptoError("消息无法解密") from exc
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
    decryptor = cipher.decryptor()
    try:
        plain = _unpad(decryptor.update(raw) + decryptor.finalize())
    except Exception as exc:
        raise WeComCryptoError("消息无法解密") from exc
    if len(plain) < 20:
        raise WeComCryptoError("消息无法解密")
    msg_len = struct.unpack(">I", plain[16:20])[0]
    message = plain[20 : 20 + msg_len]
    tail = plain[20 + msg_len :]
    if tail.decode(errors="ignore") != receive_id:
        raise WeComCryptoError("接收方不匹配")
    return message.decode()


def _pad(data: bytes) -> bytes:
    pad = _BLOCK - (len(data) % _BLOCK)
    return data + bytes([pad]) * pad


def _unpad(data: bytes) -> bytes:
    if not data:
        raise WeComCryptoError("消息无法解密")
    pad = data[-1]
    if pad < 1 or pad > _BLOCK or data[-pad:] != bytes([pad]) * pad:
        raise WeComCryptoError("消息无法解密")
    return data[:-pad]

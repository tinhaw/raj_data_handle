from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from urllib.parse import parse_qs, urlparse


def extract_totp_secret(raw_secret: str) -> str:
    secret = str(raw_secret or "").strip()
    if not secret:
        raise ValueError("TOTP Secret 不能为空。")
    if secret.startswith("otpauth://"):
        parsed = urlparse(secret)
        secret = str(parse_qs(parsed.query).get("secret", [""])[0]).strip()
        if not secret:
            raise ValueError("otpauth URI 中缺少 secret 参数。")
    return secret


def generate_totp(
    raw_secret: str,
    *,
    timestamp: int | None = None,
    digits: int = 6,
    period: int = 30,
) -> str:
    normalized = extract_totp_secret(raw_secret).replace(" ", "").upper()
    padding = "=" * (-len(normalized) % 8)
    try:
        secret = base64.b32decode(normalized + padding, casefold=True)
    except Exception as exc:
        raise ValueError("TOTP Secret 不是有效的 Base32。") from exc

    current = int(time.time() if timestamp is None else timestamp)
    digest = hmac.new(
        secret,
        struct.pack(">Q", current // period),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)

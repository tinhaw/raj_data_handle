from __future__ import annotations

import base64
import hashlib
import io
import json
import random
import secrets
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image, ImageDraw, ImageFont

from packages.common.settings import Settings, get_settings

CAPTCHA_TTL_SECONDS = 180


def _key(settings: Settings) -> bytes:
    return hashlib.sha256(f"captcha:{settings.secret_key}".encode()).digest()


def _encrypt(payload: dict[str, object], settings: Settings) -> str:
    nonce = secrets.token_bytes(12)
    plaintext = json.dumps(payload, separators=(",", ":")).encode()
    ciphertext = AESGCM(_key(settings)).encrypt(nonce, plaintext, b"raj-captcha-v1")
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def _decrypt(token: str, settings: Settings) -> dict[str, object]:
    raw = base64.urlsafe_b64decode(token.encode())
    plaintext = AESGCM(_key(settings)).decrypt(raw[:12], raw[12:], b"raj-captcha-v1")
    value = json.loads(plaintext.decode())
    if not isinstance(value, dict):
        raise ValueError("invalid captcha")
    return value


def _render_image(question: str) -> str:
    image = Image.new("RGB", (150, 52), color=(247, 250, 252))
    draw = ImageDraw.Draw(image)
    for _ in range(18):
        x1, y1 = random.randint(0, 149), random.randint(0, 51)
        x2, y2 = random.randint(0, 149), random.randint(0, 51)
        draw.line((x1, y1, x2, y2), fill=(190, 204, 218), width=1)
    font = ImageFont.load_default(size=22)
    draw.text((28, 14), question, fill=(29, 78, 104), font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"


def create_captcha(settings: Settings | None = None) -> tuple[str, str, datetime]:
    current_settings = settings or get_settings()
    left = random.randint(1, 9)
    right = random.randint(1, 9)
    operator = random.choice(("+", "-"))
    if operator == "-" and right > left:
        left, right = right, left
    answer = left + right if operator == "+" else left - right
    expires_at = datetime.now(UTC) + timedelta(seconds=CAPTCHA_TTL_SECONDS)
    token = _encrypt(
        {"answer": answer, "exp": int(expires_at.timestamp()), "nonce": secrets.token_hex(8)},
        current_settings,
    )
    return token, _render_image(f"{left} {operator} {right} = ?"), expires_at


def verify_captcha(
    captcha_id: str,
    captcha_code: str,
    settings: Settings | None = None,
) -> bool:
    current_settings = settings or get_settings()
    try:
        payload = _decrypt(captcha_id, current_settings)
        if int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
            return False
        return secrets.compare_digest(str(payload["answer"]), captcha_code.strip())
    except (ValueError, KeyError, TypeError):
        return False

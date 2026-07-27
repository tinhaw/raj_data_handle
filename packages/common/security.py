from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwt

from packages.common.settings import Settings, get_settings

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "raj-data-handle"
PASSWORD_MIN_LENGTH = 10


class SecurityValidationError(ValueError):
    pass


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def validate_password(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise SecurityValidationError(f"密码至少需要 {PASSWORD_MIN_LENGTH} 个字符。")
    if len(password.encode("utf-8")) > 72:
        raise SecurityValidationError("密码过长，请控制在 72 个 UTF-8 字节以内。")


def hash_password(password: str) -> str:
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def optional_fingerprint(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return sha256_text(normalized) if normalized else None


def new_session_secret() -> str:
    return secrets.token_urlsafe(32)


def create_session_jwt(
    *,
    user_id: int,
    role: str,
    session_secret: str,
    expires_at: datetime,
    settings: Settings | None = None,
) -> str:
    current_settings = settings or get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "sid": session_secret,
        "iss": JWT_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, current_settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_session_jwt(token: str, settings: Settings | None = None) -> dict[str, Any]:
    current_settings = settings or get_settings()
    try:
        return jwt.decode(
            token,
            current_settings.secret_key,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
        )
    except JWTError as exc:
        raise SecurityValidationError("登录会话无效或已过期。") from exc


def session_expiry(settings: Settings | None = None) -> datetime:
    current_settings = settings or get_settings()
    return datetime.now(UTC) + timedelta(minutes=current_settings.session_ttl_minutes)


def _credential_key(settings: Settings) -> bytes:
    configured = (settings.credential_encryption_key or "").strip()
    if configured:
        try:
            key = base64.urlsafe_b64decode(configured.encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise SecurityValidationError(
                "RAJ_CREDENTIAL_ENCRYPTION_KEY 不是有效 Base64。"
            ) from exc
        if len(key) != 32:
            raise SecurityValidationError("RAJ_CREDENTIAL_ENCRYPTION_KEY 解码后必须为 32 字节。")
        return key
    if settings.is_production:
        raise SecurityValidationError("生产环境必须配置 RAJ_CREDENTIAL_ENCRYPTION_KEY。")
    return hashlib.sha256(f"credential:{settings.secret_key}".encode()).digest()


def encrypt_credentials(
    payload: dict[str, str],
    *,
    source_id: str,
    credential_version: int,
    settings: Settings | None = None,
) -> str:
    current_settings = settings or get_settings()
    nonce = secrets.token_bytes(12)
    aad = f"{source_id}:{credential_version}".encode()
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_credential_key(current_settings)).encrypt(nonce, plaintext, aad)
    return "v1:" + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_credentials(
    encrypted: str,
    *,
    source_id: str,
    credential_version: int,
    settings: Settings | None = None,
) -> dict[str, str]:
    current_settings = settings or get_settings()
    if not encrypted.startswith("v1:"):
        raise SecurityValidationError("不支持的凭据密文版本。")
    try:
        raw = base64.urlsafe_b64decode(encrypted[3:].encode("ascii"))
        if len(raw) < 29:
            raise ValueError
        nonce, ciphertext = raw[:12], raw[12:]
        aad = f"{source_id}:{credential_version}".encode()
        plaintext = AESGCM(_credential_key(current_settings)).decrypt(nonce, ciphertext, aad)
        value = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise SecurityValidationError("凭据密文无效或无法解密。") from exc
    if not isinstance(value, dict):
        raise SecurityValidationError("凭据内容格式无效。")
    return {str(key): str(item) for key, item in value.items()}

from datetime import UTC, datetime, timedelta

import pytest

from packages.common.security import (
    SecurityValidationError,
    create_session_jwt,
    decode_session_jwt,
    decrypt_credentials,
    encrypt_credentials,
    hash_password,
    validate_password,
    verify_password,
)
from packages.common.settings import Settings


def settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def test_password_hash_round_trip() -> None:
    password_hash = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("incorrect password", password_hash)


def test_short_password_is_rejected() -> None:
    with pytest.raises(SecurityValidationError):
        validate_password("short")


def test_credentials_are_bound_to_source_and_version() -> None:
    configured = settings()
    encrypted = encrypt_credentials(
        {"username": "operator", "password": "secret", "totp_secret": "ABC"},
        source_id="rajwin",
        credential_version=2,
        settings=configured,
    )
    assert "operator" not in encrypted
    assert decrypt_credentials(
        encrypted,
        source_id="rajwin",
        credential_version=2,
        settings=configured,
    ) == {
        "username": "operator",
        "password": "secret",
        "totp_secret": "ABC",
    }
    with pytest.raises(SecurityValidationError):
        decrypt_credentials(
            encrypted,
            source_id="rajluck",
            credential_version=2,
            settings=configured,
        )


def test_expired_session_jwt_is_rejected() -> None:
    configured = settings()
    token = create_session_jwt(
        user_id=1,
        role="admin",
        session_secret="session-secret",
        expires_at=datetime.now(UTC) - timedelta(seconds=5),
        settings=configured,
    )
    with pytest.raises(SecurityValidationError):
        decode_session_jwt(token, configured)

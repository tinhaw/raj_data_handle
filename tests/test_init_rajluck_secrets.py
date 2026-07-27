import base64

import pytest

from deploy.init_rajluck_secrets import (
    SecretFileError,
    build_secrets_file,
    write_secrets_file,
)
from deploy.render_rajluck_env import read_env_file


def test_creates_private_secret_file_without_placeholders(tmp_path) -> None:
    target = tmp_path / "raj-data-handle.env"
    write_secrets_file(
        target,
        build_secrets_file(),
        force=False,
    )

    values = read_env_file(target)
    assert target.stat().st_mode & 0o777 == 0o600
    assert len(values["RAJ_SECRET_KEY"]) >= 32
    assert len(base64.urlsafe_b64decode(values["RAJ_CREDENTIAL_ENCRYPTION_KEY"])) == 32
    assert values["RAJ_RDS_USERNAME"] == ""
    assert values["RAJ_RDS_PASSWORD"] == ""
    assert "RAJ_CORS_ORIGINS" not in values
    assert "WEB_PORT" not in values
    assert "CHANGE_ME" not in target.read_text(encoding="utf-8")


def test_generated_file_omits_yaml_owned_web_settings() -> None:
    contents = build_secrets_file()
    assert "RAJ_SESSION_COOKIE_SECURE" not in contents
    assert "RAJ_CORS_ORIGINS" not in contents
    assert "WEB_BIND_ADDRESS" not in contents
    assert "WEB_PORT" not in contents


def test_requires_explicit_overwrite(tmp_path) -> None:
    target = tmp_path / "raj-data-handle.env"
    write_secrets_file(target, build_secrets_file(), force=False)
    with pytest.raises(SecretFileError, match="refusing to overwrite"):
        write_secrets_file(target, build_secrets_file(), force=False)

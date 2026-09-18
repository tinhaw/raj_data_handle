import pytest

from packages.common.settings import Settings
from packages.domain.services.remote_account_identity import (
    RemoteAccountIdentityValidationError,
    normalize_remote_market_base_url,
    normalize_remote_market_code,
    normalize_remote_username,
    remote_account_credential_scope,
)


def development_settings() -> Settings:
    return Settings(
        environment="development",
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def test_remote_market_code_is_uppercase_for_analysis_and_erp() -> None:
    assert normalize_remote_market_code(" raj-spin_1 ") == "RAJ-SPIN_1"

    with pytest.raises(RemoteAccountIdentityValidationError):
        normalize_remote_market_code("raj spin")


def test_remote_market_url_strips_its_optional_api_suffix() -> None:
    settings = development_settings()
    assert (
        normalize_remote_market_base_url("https://erp.example.test/api/", settings)
        == "https://erp.example.test"
    )
    assert normalize_remote_market_base_url("http://localhost:9000", settings) == "http://localhost:9000"


@pytest.mark.parametrize(
    "value",
    [
        "http://erp.example.test",
        "https://user:password@erp.example.test",
        "https://erp.example.test/api/codes",
        "https://erp.example.test?token=secret",
    ],
)
def test_remote_market_url_rejects_unsafe_or_non_root_values(value: str) -> None:
    with pytest.raises(RemoteAccountIdentityValidationError):
        normalize_remote_market_base_url(value, development_settings())


def test_unified_account_scope_is_distinct_from_legacy_source_scope() -> None:
    assert remote_account_credential_scope("account-123") == "remote-account:account-123"
    assert remote_account_credential_scope("account-123") != "account-123"


def test_remote_username_is_nonempty_but_not_a_market_code() -> None:
    assert normalize_remote_username("  account@example  ") == "account@example"
    with pytest.raises(RemoteAccountIdentityValidationError):
        normalize_remote_username("   ")

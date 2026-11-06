from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import (
    SecurityValidationError,
    decrypt_credentials,
    encrypt_credentials,
)
from packages.common.settings import Settings, get_settings
from packages.domain.models import (
    DataDictionaryEntry,
    PaymentChannelBinding,
    PaymentPlatform,
    ReconciliationBatch,
    SourceConfig,
)
from packages.domain.schemas.source import (
    SourceCreateRequest,
    SourcePatchRequest,
    SourceUpsertRequest,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.data_dictionary_service import (
    DataDictionarySyncError,
    ensure_charge_statuses,
    ensure_spin_order_statuses,
    sync_payment_channel_names,
    sync_payment_channels,
)
from packages.domain.services.erp_compatibility_id_service import (
    register_erp_compatibility_id,
)
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialsError,
    decrypt_remote_account_credentials,
    resolve_default_remote_account_credentials,
)
from packages.domain.services.remote_account_session_service import account_session
from packages.domain.services.remote_charge_service import RajAdminChargeClient, RemoteChargeError
from packages.domain.services.remote_scoring_review_service import (
    RemoteScoringReviewError,
    ScoringReviewRemoteClient,
)

SOURCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class SourceValidationError(ValueError):
    pass


class SourceConflictError(SourceValidationError):
    pass


class SourceNotFoundError(SourceValidationError):
    pass


def validate_source_id(value: str) -> str:
    normalized = value.strip()
    if not SOURCE_ID_PATTERN.fullmatch(normalized):
        raise SourceValidationError(
            "来源 ID 必须为 2-64 位，以小写字母开头，且只能包含小写字母、数字、下划线和连字符。"
        )
    return normalized


def validate_timezone(value: str) -> str:
    normalized = value.strip()
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise SourceValidationError("业务时区必须是有效 IANA TZDB 标识。") from exc
    return normalized


def normalize_base_url(value: str | None, settings: Settings) -> str | None:
    if value is None:
        return None
    parts = urlsplit(value.strip())
    if parts.username or parts.password or parts.query or parts.fragment:
        raise SourceValidationError("Base URL 不能包含凭据、查询参数或片段。")
    is_local_dev = settings.environment == "development" and parts.hostname in {
        "localhost",
        "127.0.0.1",
    }
    if parts.scheme != "https" and not (is_local_dev and parts.scheme == "http"):
        raise SourceValidationError("Base URL 必须使用 HTTPS。")
    if not parts.hostname:
        raise SourceValidationError("Base URL 缺少有效主机名。")
    path = parts.path.rstrip("/")
    if path not in {"", "/"}:
        raise SourceValidationError("Base URL 不能包含业务接口路径。")
    return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")


def _normalize_key_api_base_url(
    value: str | None,
    settings: Settings,
    *,
    label: str,
) -> str | None:
    """Normalize a write-only-key API root that must end in ``/api``."""

    if value is None:
        return None
    parts = urlsplit(value.strip())
    if parts.username or parts.password or parts.query or parts.fragment:
        raise SourceValidationError(f"{label} Base URL 不能包含凭据、查询参数或片段。")
    is_local_dev = settings.environment == "development" and parts.hostname in {
        "localhost",
        "127.0.0.1",
    }
    if parts.scheme != "https" and not (is_local_dev and parts.scheme == "http"):
        raise SourceValidationError(f"{label} Base URL 必须使用 HTTPS。")
    if not parts.hostname:
        raise SourceValidationError(f"{label} Base URL 缺少有效主机名。")
    if parts.path.rstrip("/") != "/api":
        raise SourceValidationError(f"{label} Base URL 必须以 /api 结束。")
    return urlunsplit((parts.scheme, parts.netloc, "/api", "", ""))


def normalize_scoring_api_base_url(value: str | None, settings: Settings) -> str | None:
    """Normalize an external scoring-review API root, including its ``/api`` path.

    This deliberately differs from :func:`normalize_base_url`: Raj admin
    connections start at a host root, while the documented scoring API base is
    ``https://<host>/api``.  Keeping the paths separate prevents an admin URL
    from being accidentally used as an API-key endpoint.
    """

    return _normalize_key_api_base_url(value, settings, label="评分审核 API")


def normalize_initial_review_v1_api_base_url(value: str | None, settings: Settings) -> str | None:
    """Normalize the v1 initial-review API root using the same ``/api`` contract."""

    return _normalize_key_api_base_url(value, settings, label="v1版初审 API")


def _scoring_api_credential_scope(source_id: str) -> str:
    """Return a distinct AES-GCM associated-data scope for the API key."""

    return f"{source_id}:scoring-review-api"


def _initial_review_v1_api_credential_scope(source_id: str) -> str:
    """Keep v1 initial-review keys cryptographically separate from other keys."""

    return f"{source_id}:initial-review-v1-api"


def _credentials_dict(request: object) -> dict[str, str | None]:
    if request is None:
        return {}
    return {
        "username": getattr(request, "username", None),
        "password": getattr(request, "password", None),
        "totp_secret": getattr(request, "totp_secret", None),
    }


async def list_sources(session: AsyncSession, enabled: bool | None = None) -> list[SourceConfig]:
    statement = select(SourceConfig).order_by(
        SourceConfig.display_order.asc(), SourceConfig.source_id.asc()
    )
    if enabled is not None:
        statement = statement.where(SourceConfig.enabled.is_(enabled))
    result = await session.scalars(statement)
    return list(result)


def source_login_username(
    source: SourceConfig,
    *,
    settings: Settings | None = None,
) -> str | None:
    """Return only a source's login account for the administrator settings UI.

    Passwords and TOTP secrets remain write-only.  A malformed historical
    ciphertext should not prevent the settings page from loading; the normal
    credential update flow will surface that condition if it needs changing.
    """

    if not source.encrypted_credentials:
        return None
    try:
        credentials = decrypt_credentials(
            source.encrypted_credentials,
            source_id=source.source_id,
            credential_version=source.credential_version,
            settings=settings,
        )
    except SecurityValidationError:
        return None
    username = credentials.get("username", "").strip()
    return username or None


async def reorder_sources(
    session: AsyncSession,
    *,
    source_ids: list[str],
    actor_user_id: int,
) -> list[SourceConfig]:
    normalized_ids = [validate_source_id(source_id) for source_id in source_ids]
    if len(normalized_ids) != len(set(normalized_ids)):
        raise SourceValidationError("盘口顺序不能包含重复项。")

    sources = list(await session.scalars(select(SourceConfig)))
    current_ids = {source.source_id for source in sources}
    if set(normalized_ids) != current_ids:
        raise SourceValidationError("盘口顺序必须包含全部盘口，且不能包含不存在的盘口。")

    source_by_id = {source.source_id: source for source in sources}
    for display_order, source_id in enumerate(normalized_ids, start=1):
        source = source_by_id[source_id]
        source.display_order = display_order
        source.updated_by = actor_user_id

    await write_audit(
        session,
        action="source.reorder",
        actor_user_id=actor_user_id,
        target_type="source",
        metadata={"source_ids": normalized_ids},
    )
    await session.commit()
    return [source_by_id[source_id] for source_id in normalized_ids]


async def get_source(session: AsyncSession, source_id: str) -> SourceConfig:
    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise SourceNotFoundError("盘口配置不存在。")
    return source


async def create_source(
    session: AsyncSession,
    *,
    request: SourceCreateRequest,
    actor_user_id: int,
    settings: Settings | None = None,
) -> SourceConfig:
    source_id = validate_source_id(request.source_id)
    if await session.get(SourceConfig, source_id) is not None:
        raise SourceConflictError("来源 ID 已存在，请使用其他 ID。")
    if request.enabled:
        raise SourceValidationError("新增盘口必须先保存为停用草稿，连接测试通过后才能启用。")
    try:
        return await upsert_source(
            session,
            source_id=source_id,
            request=request,
            actor_user_id=actor_user_id,
            settings=settings,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise SourceConflictError("来源 ID 已存在，请使用其他 ID。") from exc


async def upsert_source(
    session: AsyncSession,
    *,
    source_id: str,
    request: SourceUpsertRequest | SourcePatchRequest,
    actor_user_id: int,
    settings: Settings | None = None,
) -> SourceConfig:
    source_id = validate_source_id(source_id)
    current_settings = settings or get_settings()
    source = await session.get(SourceConfig, source_id)
    creating = source is None
    if source is None:
        if not isinstance(request, SourceUpsertRequest):
            raise SourceValidationError("盘口配置不存在。")
        max_display_order = await session.scalar(select(func.max(SourceConfig.display_order)))
        source = SourceConfig(
            source_id=source_id,
            display_name=request.display_name,
            display_order=(max_display_order or 0) + 1,
            business_timezone=current_settings.default_business_timezone,
            currency=current_settings.default_currency,
            credential_version=0,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        session.add(source)

    changed_fields: list[str] = []
    previous_base_url = source.base_url
    for field in ("display_name", "business_timezone", "currency"):
        value = getattr(request, field, None)
        if value is None:
            continue
        if field == "business_timezone":
            value = validate_timezone(value)
        if field == "currency":
            value = value.upper()
        if getattr(source, field) != value:
            setattr(source, field, value)
            changed_fields.append(field)

    if isinstance(request, SourceUpsertRequest) or request.base_url is not None:
        raw_url = str(request.base_url) if request.base_url is not None else None
        base_url = normalize_base_url(raw_url, current_settings)
        if previous_base_url != base_url:
            source.base_url = base_url
            source.last_test_status = None
            changed_fields.append("base_url")

    credentials_changed = False
    credential_input = _credentials_dict(request.credentials)
    provided = {
        key: value.strip() for key, value in credential_input.items() if value and value.strip()
    }
    if provided:
        existing: dict[str, str] = {}
        if source.encrypted_credentials:
            try:
                existing = decrypt_credentials(
                    source.encrypted_credentials,
                    source_id=source.source_id,
                    credential_version=source.credential_version,
                    settings=current_settings,
                )
            except SecurityValidationError as exc:
                raise SourceValidationError("已保存凭据无法解密，请清除后重新配置。") from exc
        existing.update(provided)
        required = {"username", "password", "totp_secret"}
        if not required.issubset(existing):
            raise SourceValidationError("首次配置必须同时提供账号、密码和 TOTP Secret。")
        source.credential_version = (source.credential_version or 0) + 1
        source.encrypted_credentials = encrypt_credentials(
            existing,
            source_id=source.source_id,
            credential_version=source.credential_version,
            settings=current_settings,
        )
        source.credential_updated_at = datetime.now(UTC)
        source.last_test_status = None
        credentials_changed = True
        changed_fields.append("credentials")

    scoring_api = getattr(request, "scoring_api", None)
    if scoring_api is not None:
        raw_scoring_api_url = (
            str(scoring_api.base_url) if scoring_api.base_url is not None else None
        )
        scoring_api_base_url = normalize_scoring_api_base_url(
            raw_scoring_api_url,
            current_settings,
        )
        if source.scoring_api_base_url != scoring_api_base_url:
            source.scoring_api_base_url = scoring_api_base_url
            source.scoring_api_last_test_status = None
            changed_fields.append("scoring_api_base_url")

        supplied_api_key = (scoring_api.api_key or "").strip()
        if supplied_api_key:
            if scoring_api_base_url is None:
                raise SourceValidationError("配置评分审核 API Key 前必须填写 Base URL。")
            source.scoring_api_key_version = (source.scoring_api_key_version or 0) + 1
            source.encrypted_scoring_api_key = encrypt_credentials(
                {"api_key": supplied_api_key},
                source_id=_scoring_api_credential_scope(source.source_id),
                credential_version=source.scoring_api_key_version,
                settings=current_settings,
            )
            source.scoring_api_key_updated_at = datetime.now(UTC)
            source.scoring_api_last_test_status = None
            changed_fields.append("scoring_api_key")
        elif scoring_api_base_url is None and source.encrypted_scoring_api_key is not None:
            # Clearing the URL explicitly clears the inaccessible key too.
            # A new version makes a copied historical ciphertext unusable.
            source.scoring_api_key_version = (source.scoring_api_key_version or 0) + 1
            source.encrypted_scoring_api_key = None
            source.scoring_api_key_updated_at = datetime.now(UTC)
            source.scoring_api_last_test_status = None
            changed_fields.append("scoring_api_key")

    initial_review_v1_api = getattr(request, "initial_review_v1_api", None)
    if initial_review_v1_api is not None:
        raw_initial_review_v1_api_url = (
            str(initial_review_v1_api.base_url)
            if initial_review_v1_api.base_url is not None
            else None
        )
        initial_review_v1_api_base_url = normalize_initial_review_v1_api_base_url(
            raw_initial_review_v1_api_url,
            current_settings,
        )
        if source.initial_review_v1_api_base_url != initial_review_v1_api_base_url:
            source.initial_review_v1_api_base_url = initial_review_v1_api_base_url
            changed_fields.append("initial_review_v1_api_base_url")

        supplied_initial_review_v1_api_key = (initial_review_v1_api.api_key or "").strip()
        if supplied_initial_review_v1_api_key:
            if initial_review_v1_api_base_url is None:
                raise SourceValidationError("配置 v1版初审 API Key 前必须填写 Base URL。")
            source.initial_review_v1_api_key_version = (
                source.initial_review_v1_api_key_version or 0
            ) + 1
            source.encrypted_initial_review_v1_api_key = encrypt_credentials(
                {"api_key": supplied_initial_review_v1_api_key},
                source_id=_initial_review_v1_api_credential_scope(source.source_id),
                credential_version=source.initial_review_v1_api_key_version,
                settings=current_settings,
            )
            source.initial_review_v1_api_key_updated_at = datetime.now(UTC)
            changed_fields.append("initial_review_v1_api_key")
        elif (
            initial_review_v1_api_base_url is None
            and source.encrypted_initial_review_v1_api_key is not None
        ):
            # Clearing the URL explicitly clears the inaccessible key too.
            source.initial_review_v1_api_key_version = (
                source.initial_review_v1_api_key_version or 0
            ) + 1
            source.encrypted_initial_review_v1_api_key = None
            source.initial_review_v1_api_key_updated_at = datetime.now(UTC)
            changed_fields.append("initial_review_v1_api_key")

    requested_enabled = getattr(request, "enabled", None)
    if requested_enabled is not None:
        if requested_enabled:
            if not source.base_url:
                raise SourceValidationError("启用前必须配置 Base URL。")
            credential_envelope = await resolve_default_remote_account_credentials(
                session,
                source=source,
            )
            if credential_envelope is None:
                raise SourceValidationError("启用前必须配置一个已启用的默认远端账号。")
        if source.enabled != requested_enabled:
            source.enabled = requested_enabled
            changed_fields.append("enabled")

    if credentials_changed or "base_url" in changed_fields:
        source.enabled = False
    if changed_fields and not creating:
        source.config_version += 1
    source.updated_by = actor_user_id
    if creating:
        await session.flush()
        await register_erp_compatibility_id(
            session,
            entity_type="source",
            canonical_id=source.source_id,
        )
        await ensure_charge_statuses(session, source_id=source.source_id)
        await ensure_spin_order_statuses(session, source_id=source.source_id)
    await write_audit(
        session,
        action="source.create" if creating else "source.update",
        actor_user_id=actor_user_id,
        target_type="source",
        target_id=source_id,
        metadata={"changed_fields": sorted(set(changed_fields))},
    )
    await session.commit()
    return source


async def delete_source(
    session: AsyncSession,
    *,
    source_id: str,
    actor_user_id: int,
) -> None:
    source = await get_source(session, source_id)
    if source.enabled:
        raise SourceConflictError("请先停用盘口，再执行删除。")
    historical_batch_id = await session.scalar(
        select(ReconciliationBatch.id)
        .where(ReconciliationBatch.source_id == source.source_id)
        .limit(1)
    )
    if historical_batch_id is not None:
        raise SourceConflictError("该盘口已有历史比对批次，不能删除；可保持停用状态。")

    await session.execute(
        delete(PaymentChannelBinding).where(PaymentChannelBinding.source_id == source.source_id)
    )
    await session.execute(
        delete(DataDictionaryEntry).where(DataDictionaryEntry.source_id == source.source_id)
    )
    await write_audit(
        session,
        action="source.delete",
        actor_user_id=actor_user_id,
        target_type="source",
        target_id=source.source_id,
        metadata={"display_name": source.display_name},
    )
    await session.delete(source)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise SourceConflictError("盘口已被业务数据引用，不能删除；可保持停用状态。") from exc


async def clear_credentials(
    session: AsyncSession,
    *,
    source_id: str,
    actor_user_id: int,
) -> SourceConfig:
    source = await get_source(session, source_id)
    source.encrypted_credentials = None
    source.credential_version += 1
    source.credential_updated_at = datetime.now(UTC)
    source.last_test_status = None
    source.enabled = False
    source.config_version += 1
    source.updated_by = actor_user_id
    await write_audit(
        session,
        action="source.credentials.clear",
        actor_user_id=actor_user_id,
        target_type="source",
        target_id=source_id,
    )
    await session.commit()
    return source


async def test_source_scoring_api_connection(
    session: AsyncSession,
    *,
    source_id: str,
    actor_user_id: int,
) -> tuple[SourceConfig, str]:
    """Validate the external API's low-volume Excel export independently."""

    source = await get_source(session, source_id)
    if not source.scoring_api_base_url or not source.encrypted_scoring_api_key:
        raise SourceValidationError("请先保存评分审核 API Base URL 和 API Key。")
    request_id = uuid.uuid4().hex
    settings = get_settings()
    try:
        payload = decrypt_credentials(
            source.encrypted_scoring_api_key,
            source_id=_scoring_api_credential_scope(source.source_id),
            credential_version=source.scoring_api_key_version,
            settings=settings,
        )
        api_key = payload["api_key"]
    except (SecurityValidationError, KeyError) as exc:
        raise SourceValidationError("已保存的评分审核 API Key 无法解密，请重新配置。") from exc

    test_status = "failed"
    try:
        async with ScoringReviewRemoteClient(
            base_url=source.scoring_api_base_url,
            api_key=api_key,
        ) as client:
            await client.test_connection()
        test_status = "passed"
    except RemoteScoringReviewError:
        test_status = "failed"
    source.scoring_api_last_tested_at = datetime.now(UTC)
    source.scoring_api_last_test_status = test_status
    source.scoring_api_last_test_request_id = request_id
    await write_audit(
        session,
        action="source.scoring_api.connection_test",
        actor_user_id=actor_user_id,
        target_type="source",
        target_id=source.source_id,
        result=test_status,
        metadata={"request_id": request_id},
    )
    await session.commit()
    return source, request_id


def _platform_key_for_channel(label: str) -> str | None:
    normalized = "".join(label.lower().split())
    if "aelopay" in normalized:
        return "aelopay"
    if "elepay" in normalized:
        return "elepay"
    return None


async def _sync_known_channels(
    session: AsyncSession,
    *,
    source: SourceConfig,
    channels: list[dict[str, str]],
    actor_user_id: int,
) -> int:
    platforms = {item.platform_key: item for item in await session.scalars(select(PaymentPlatform))}
    existing_bindings = list(
        await session.scalars(
            select(PaymentChannelBinding).where(
                PaymentChannelBinding.source_id == source.source_id,
                PaymentChannelBinding.business_type == "payin",
            )
        )
    )
    for binding in existing_bindings:
        binding.active = False
    synced = 0
    for channel in channels:
        platform_key = _platform_key_for_channel(channel["label"])
        platform = platforms.get(platform_key or "")
        if platform is None:
            continue
        binding = await session.scalar(
            select(PaymentChannelBinding).where(
                PaymentChannelBinding.source_id == source.source_id,
                PaymentChannelBinding.business_type == "payin",
                PaymentChannelBinding.remote_channel_code == channel["code"],
                PaymentChannelBinding.platform_id == platform.id,
            )
        )
        if binding is None:
            binding = PaymentChannelBinding(
                platform_id=platform.id,
                source_id=source.source_id,
                business_type="payin",
                remote_channel_code=channel["code"],
                remote_channel_label=channel["label"],
                active=True,
                created_by=actor_user_id,
            )
            session.add(binding)
        else:
            binding.remote_channel_label = channel["label"]
            binding.active = True
        synced += 1
    return synced


async def test_source_connection(
    session: AsyncSession,
    *,
    source_id: str,
    actor_user_id: int,
) -> tuple[SourceConfig, str]:
    source = await get_source(session, source_id)
    if not source.base_url:
        raise SourceValidationError("请先保存 Base URL。")
    request_id = uuid.uuid4().hex
    settings = get_settings()
    credential_envelope = await resolve_default_remote_account_credentials(
        session,
        source=source,
    )
    if credential_envelope is None:
        raise SourceValidationError("请先配置一个已启用的默认远端账号。")
    try:
        credentials = decrypt_remote_account_credentials(
            credential_envelope,
            settings=settings,
        )
    except RemoteAccountCredentialsError as exc:
        raise SourceValidationError("已保存凭据无法解密，请清除后重新配置。") from exc
    test_status = "failed"
    synced_channels = 0
    dictionary_entries = 0
    payment_dictionary_entries = 0
    try:
        async with RajAdminChargeClient(
            remote_session=account_session(
                session, envelope=credential_envelope, base_url=source.base_url, settings=settings
            ),
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
        ) as client:
            await client.login()
            channel_names = await client.fetch_channels()
            payment_channels = await client.fetch_payment_channels()
        channel_dictionary_sync = await sync_payment_channels(
            session,
            source_id=source.source_id,
            channels=payment_channels,
        )
        payment_dictionary_entries = channel_dictionary_sync.active_entries
        channel_name_dictionary_sync = await sync_payment_channel_names(
            session,
            source_id=source.source_id,
            channels=channel_names,
        )
        dictionary_entries = channel_name_dictionary_sync.active_entries
        synced_channels = await _sync_known_channels(
            session,
            source=source,
            channels=channel_names,
            actor_user_id=actor_user_id,
        )
        test_status = "passed"
    except (RemoteChargeError, DataDictionarySyncError, KeyError):
        test_status = "failed"
    source.last_tested_at = datetime.now(UTC)
    source.last_test_status = test_status
    source.last_test_request_id = request_id
    await write_audit(
        session,
        action="source.connection_test",
        actor_user_id=actor_user_id,
        target_type="source",
        target_id=source_id,
        result=test_status,
        metadata={
            "request_id": request_id,
            "synced_payment_channels": payment_dictionary_entries,
            "synced_payment_channel_names": dictionary_entries,
            "synced_known_payin_channels": synced_channels,
        },
    )
    await session.commit()
    return source, request_id

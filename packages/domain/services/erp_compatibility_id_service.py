"""Stable numeric-ID crosswalk for the online ERP compatibility contract."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import ErpCompatibilityIdMap

ERP_COMPATIBILITY_ENTITY_TYPES = frozenset(
    {
        "operator",
        "operator_line",
        "daily_balance",
        "period_lock",
        "import_job",
        "import_job_row",
        "redemption_campaign",
        "redemption_campaign_tier",
        "redemption_task",
        "redemption_batch",
        "redemption_issue",
        "source",
        "remote_account",
    }
)
# Current UUID/string projections live above this JavaScript-safe boundary so
# the online ERP's original positive Long IDs can later be imported verbatim.
ERP_COMPATIBILITY_PROJECTION_ID_BASE = 9_000_000_000_000


class ErpCompatibilityIdError(RuntimeError):
    pass


def _validate_entity_type(entity_type: str) -> str:
    if entity_type not in ERP_COMPATIBILITY_ENTITY_TYPES:
        raise ErpCompatibilityIdError(f"不支持的 ERP 兼容实体类型：{entity_type}")
    return entity_type


async def register_erp_compatibility_id(
    session: AsyncSession,
    *,
    entity_type: str,
    canonical_id: str,
) -> int:
    """Create or reuse a mapping in the caller's existing transaction."""

    normalized_type = _validate_entity_type(entity_type)
    normalized_id = canonical_id.strip()
    if not normalized_id:
        raise ErpCompatibilityIdError("ERP 兼容映射的当前实体 ID 不能为空。")
    existing = await session.scalar(
        select(ErpCompatibilityIdMap).where(
            ErpCompatibilityIdMap.entity_type == normalized_type,
            ErpCompatibilityIdMap.canonical_id == normalized_id,
        )
    )
    if existing is not None:
        if existing.legacy_id is None:
            raise ErpCompatibilityIdError("ERP 兼容 ID 映射尚未完成初始化。")
        return existing.legacy_id
    mapping = ErpCompatibilityIdMap(
        entity_type=normalized_type,
        canonical_id=normalized_id,
    )
    session.add(mapping)
    await session.flush()
    mapping.legacy_id = ERP_COMPATIBILITY_PROJECTION_ID_BASE + mapping.mapping_id
    await session.flush()
    if mapping.legacy_id is None:  # pragma: no cover - guarded by the assignment above
        raise ErpCompatibilityIdError("ERP 兼容 ID 映射初始化失败。")
    return mapping.legacy_id


async def bind_erp_compatibility_id(
    session: AsyncSession,
    *,
    entity_type: str,
    canonical_id: str,
    legacy_id: int,
) -> int:
    """Bind an exact online ERP ID while importing historical data."""

    normalized_type = _validate_entity_type(entity_type)
    normalized_id = canonical_id.strip()
    if not normalized_id or legacy_id < 1:
        raise ErpCompatibilityIdError("ERP 历史兼容映射必须包含有效的当前 ID 和正整数 ID。")
    canonical_mapping = await session.scalar(
        select(ErpCompatibilityIdMap).where(
            ErpCompatibilityIdMap.entity_type == normalized_type,
            ErpCompatibilityIdMap.canonical_id == normalized_id,
        )
    )
    if canonical_mapping is not None:
        if canonical_mapping.legacy_id != legacy_id:
            raise ErpCompatibilityIdError("当前记录已绑定其他线上 ERP ID。")
        return legacy_id
    legacy_mapping = await session.scalar(
        select(ErpCompatibilityIdMap).where(
            ErpCompatibilityIdMap.entity_type == normalized_type,
            ErpCompatibilityIdMap.legacy_id == legacy_id,
        )
    )
    if legacy_mapping is not None:
        raise ErpCompatibilityIdError("该线上 ERP ID 已绑定其他当前记录。")
    session.add(
        ErpCompatibilityIdMap(
            entity_type=normalized_type,
            canonical_id=normalized_id,
            legacy_id=legacy_id,
        )
    )
    await session.flush()
    return legacy_id


async def get_erp_compatibility_ids(
    session: AsyncSession,
    *,
    entity_type: str,
    canonical_ids: Collection[str],
) -> dict[str, int]:
    """Read an already-provisioned crosswalk without mutating a GET request."""

    normalized_type = _validate_entity_type(entity_type)
    requested = {value.strip() for value in canonical_ids if value and value.strip()}
    if not requested:
        return {}
    rows = list(
        await session.scalars(
            select(ErpCompatibilityIdMap).where(
                ErpCompatibilityIdMap.entity_type == normalized_type,
                ErpCompatibilityIdMap.canonical_id.in_(requested),
            )
        )
    )
    result = {
        row.canonical_id: row.legacy_id
        for row in rows
        if row.legacy_id is not None
    }
    missing = sorted(requested.difference(result))
    if missing:
        raise ErpCompatibilityIdError(
            f"{normalized_type} 缺少 ERP 兼容 ID 映射：{', '.join(missing)}"
        )
    return result

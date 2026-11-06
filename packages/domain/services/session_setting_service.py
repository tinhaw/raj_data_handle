from __future__ import annotations

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import SystemSessionSetting

SESSION_SETTINGS_ID = 1


def _is_missing_session_settings_table(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return "system_session_settings" in message and (
        "does not exist" in message or "no such table" in message
    )


async def get_session_settings(
    session: AsyncSession,
    *,
    defaults: Settings | None = None,
) -> SystemSessionSetting | None:
    """Return persisted login settings, or None before the schema rollout.

    The application is intentionally deployable before the separately gated
    database migration.  During that brief interval it falls back to the
    configured 30-day default instead of blocking authentication.
    """

    try:
        row = await session.get(SystemSessionSetting, SESSION_SETTINGS_ID)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_session_settings_table(exc):
            raise
        await session.rollback()
        return None

    if row is not None:
        return row

    current_defaults = defaults or get_settings()
    row = SystemSessionSetting(
        id=SESSION_SETTINGS_ID,
        session_ttl_days=current_defaults.session_ttl_days,
    )
    session.add(row)
    await session.commit()
    return row

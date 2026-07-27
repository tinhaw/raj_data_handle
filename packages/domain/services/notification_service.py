from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import UserNotification


async def list_notifications(
    session: AsyncSession,
    *,
    user_id: int,
    unread_only: bool,
    limit: int = 50,
) -> list[UserNotification]:
    statement = (
        select(UserNotification)
        .where(UserNotification.user_id == user_id)
        .order_by(UserNotification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        statement = statement.where(UserNotification.read_at.is_(None))
    rows = list(await session.scalars(statement))
    now = datetime.now(UTC)
    changed = False
    for row in rows:
        if row.delivered_at is None:
            row.delivered_at = now
            changed = True
    if changed:
        await session.commit()
    return rows


async def mark_notification_read(
    session: AsyncSession,
    *,
    notification_id: str,
    user_id: int,
) -> bool:
    notification = await session.scalar(
        select(UserNotification).where(
            UserNotification.id == notification_id,
            UserNotification.user_id == user_id,
        )
    )
    if notification is None:
        return False
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await session.commit()
    return True


async def mark_all_notifications_read(session: AsyncSession, *, user_id: int) -> None:
    await session.execute(
        update(UserNotification)
        .where(
            UserNotification.user_id == user_id,
            UserNotification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()

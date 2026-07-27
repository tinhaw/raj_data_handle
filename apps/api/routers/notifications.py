from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context
from packages.common.database import get_db_session
from packages.domain.schemas.notification import NotificationResponse
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.notification_service import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
async def notifications(
    unread: bool = True,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[NotificationResponse]:
    rows = await list_notifications(
        session,
        user_id=auth.user.id,
        unread_only=unread,
    )
    return [NotificationResponse.model_validate(item) for item in rows]


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_notification(
    notification_id: str,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    if not await mark_notification_read(
        session,
        notification_id=notification_id,
        user_id=auth.user.id,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在。")


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all_notifications(
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await mark_all_notifications_read(session, user_id=auth.user.id)

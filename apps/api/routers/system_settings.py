from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_admin
from packages.common.database import get_db_session
from packages.domain.schemas.system_setting import (
    RetentionSettingsResponse,
    RetentionSettingsUpdateRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.system_setting_service import (
    get_retention_settings,
    update_retention_settings,
)

router = APIRouter(prefix="/system-settings", tags=["system-settings"])


@router.get("/retention", response_model=RetentionSettingsResponse)
async def retention_settings(
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> RetentionSettingsResponse:
    return RetentionSettingsResponse.model_validate(await get_retention_settings(session))


@router.patch("/retention", response_model=RetentionSettingsResponse)
async def patch_retention_settings(
    payload: RetentionSettingsUpdateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> RetentionSettingsResponse:
    return RetentionSettingsResponse.model_validate(
        await update_retention_settings(
            session,
            payload=payload,
            actor_user_id=auth.user.id,
        )
    )

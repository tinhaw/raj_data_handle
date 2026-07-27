from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_admin
from packages.common.database import get_db_session
from packages.domain.schemas.data_dictionary import DataDictionaryEntryResponse
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.data_dictionary_service import list_payment_channel_names

router = APIRouter(tags=["data-dictionaries"])


@router.get(
    "/settings/data-dictionaries/payment-channel-names",
    response_model=list[DataDictionaryEntryResponse],
)
async def payment_channel_names(
    source_id: str | None = None,
    active: bool | None = None,
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[DataDictionaryEntryResponse]:
    return await list_payment_channel_names(
        session,
        source_id=source_id,
        active=active,
    )

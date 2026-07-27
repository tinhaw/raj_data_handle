from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context
from packages.common.database import get_db_session
from packages.domain.schemas.payment_template import (
    PaymentChannelBindingResponse,
    PaymentPlatformResponse,
    PaymentTemplateResponse,
    TemplateDetectionResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.payment_template_service import (
    TemplateDetectionError,
    detect_payment_template,
    list_channel_bindings,
    list_payment_platforms,
    list_payment_templates,
)

router = APIRouter(tags=["payment-templates"])


@router.get("/payment-platforms", response_model=list[PaymentPlatformResponse])
async def payment_platforms(
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[PaymentPlatformResponse]:
    return await list_payment_platforms(session)


@router.get(
    "/payment-template-versions",
    response_model=list[PaymentTemplateResponse],
)
async def payment_templates(
    business_type: str | None = None,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[PaymentTemplateResponse]:
    return await list_payment_templates(session, business_type=business_type)


@router.post(
    "/payment-template-versions/detect",
    response_model=TemplateDetectionResponse,
)
async def detect_template(
    header_row: int = Form(1, alias="headerRow", ge=1, le=100),
    upload: UploadFile = File(...),
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> TemplateDetectionResponse:
    try:
        return await detect_payment_template(session, upload, header_row=header_row)
    except TemplateDetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/payment-channel-bindings",
    response_model=list[PaymentChannelBindingResponse],
)
async def payment_channel_bindings(
    source_id: str | None = None,
    business_type: str | None = None,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[PaymentChannelBindingResponse]:
    return await list_channel_bindings(
        session,
        source_id=source_id,
        business_type=business_type,
    )

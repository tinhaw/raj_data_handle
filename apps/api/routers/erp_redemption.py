"""Local redemption management APIs with every remote operation intentionally absent."""

from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_admin
from packages.common.database import get_db_session
from packages.domain.schemas.erp_redemption import (
    ErpRedemptionBatchCreateRequest,
    ErpRedemptionBatchDetailResponse,
    ErpRedemptionBatchResponse,
    ErpRedemptionCampaignCreateRequest,
    ErpRedemptionCampaignResponse,
    ErpRedemptionCodeImportRequest,
    ErpRedemptionLocalPublishRequest,
)
from packages.domain.services.auth_service import AuthContext, write_audit
from packages.domain.services.erp_redemption_service import (
    ErpRedemptionConflictError,
    ErpRedemptionError,
    ErpRedemptionNotFoundError,
    create_erp_redemption_batch,
    create_erp_redemption_campaign,
    get_erp_redemption_batch,
    import_erp_redemption_codes,
    list_erp_redemption_batches,
    list_erp_redemption_campaigns,
    publish_erp_redemption_batch_locally,
)

router = APIRouter(prefix="/erp/redemption", tags=["erp-redemption"])


def _api_error(exc: ErpRedemptionError) -> HTTPException:
    if isinstance(exc, ErpRedemptionNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ErpRedemptionConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _export_bytes(detail: ErpRedemptionBatchDetailResponse) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "兑换码"
    sheet.append(
        [
            "领取日期",
            "充值窗口开始",
            "充值窗口结束",
            "档位",
            "充值门槛",
            "赠金",
            "最大奖金",
            "兑换码",
            "本地参考",
            "本地状态",
        ]
    )
    for issue in detail.issues:
        sheet.append(
            [
                issue.claim_date,
                issue.deposit_window_start,
                issue.deposit_window_end,
                issue.tier_name,
                issue.min_deposit_amount,
                issue.bonus_amount,
                issue.bonus_max_amount,
                issue.redemption_code,
                issue.local_reference,
                issue.workflow_status,
            ]
        )
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = min(
            max(len(str(cell.value or "")) for cell in column) + 2,
            28,
        )
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@router.get("/campaigns", response_model=list[ErpRedemptionCampaignResponse])
async def get_campaigns(
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpRedemptionCampaignResponse]:
    return await list_erp_redemption_campaigns(session)


@router.post(
    "/campaigns",
    response_model=ErpRedemptionCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_campaign(
    payload: ErpRedemptionCampaignCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpRedemptionCampaignResponse:
    try:
        return await create_erp_redemption_campaign(
            session,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except ErpRedemptionError as exc:
        raise _api_error(exc) from exc


@router.get("/campaigns/{campaign_id}/batches", response_model=list[ErpRedemptionBatchResponse])
async def get_campaign_batches(
    campaign_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpRedemptionBatchResponse]:
    try:
        return await list_erp_redemption_batches(session, campaign_id=campaign_id)
    except ErpRedemptionError as exc:
        raise _api_error(exc) from exc


@router.post(
    "/batches",
    response_model=ErpRedemptionBatchDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_batch(
    payload: ErpRedemptionBatchCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpRedemptionBatchDetailResponse:
    try:
        return await create_erp_redemption_batch(
            session,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except ErpRedemptionError as exc:
        raise _api_error(exc) from exc


@router.get("/batches/{batch_id}", response_model=ErpRedemptionBatchDetailResponse)
async def get_batch(
    batch_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ErpRedemptionBatchDetailResponse:
    try:
        return await get_erp_redemption_batch(session, batch_id=batch_id)
    except ErpRedemptionError as exc:
        raise _api_error(exc) from exc


@router.post("/batches/{batch_id}/codes", response_model=ErpRedemptionBatchDetailResponse)
async def post_codes(
    batch_id: str,
    payload: ErpRedemptionCodeImportRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpRedemptionBatchDetailResponse:
    try:
        return await import_erp_redemption_codes(
            session,
            batch_id=batch_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except ErpRedemptionError as exc:
        raise _api_error(exc) from exc


@router.post("/batches/{batch_id}/publish-local", response_model=ErpRedemptionBatchDetailResponse)
async def post_publish_local(
    batch_id: str,
    payload: ErpRedemptionLocalPublishRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpRedemptionBatchDetailResponse:
    try:
        return await publish_erp_redemption_batch_locally(
            session,
            batch_id=batch_id,
            row_version=payload.row_version,
            actor_user_id=auth.user.id,
        )
    except ErpRedemptionError as exc:
        raise _api_error(exc) from exc


@router.get("/batches/{batch_id}/export")
async def export_batch(
    batch_id: str,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        detail = await get_erp_redemption_batch(session, batch_id=batch_id)
    except ErpRedemptionError as exc:
        raise _api_error(exc) from exc
    await write_audit(
        session,
        action="erp_redemption_batch.export",
        actor_user_id=auth.user.id,
        target_type="erp_redemption_batch",
        target_id=batch_id,
        metadata={"issue_count": len(detail.issues)},
    )
    await session.commit()
    return Response(
        content=_export_bytes(detail),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="erp-redemption-{batch_id}.xlsx"'},
    )

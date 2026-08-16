"""Local ERP delivery-company and delivery-line APIs.

The endpoints deliberately contain no calls to ERP, RajWin or RajLuck remote
systems. They become operational only after the separately gated schema
migration has been run in an approved environment.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_admin
from packages.common.database import get_db_session
from packages.domain.schemas.erp_operator import (
    ErpDeliveryLineCreateRequest,
    ErpDeliveryLinePatchRequest,
    ErpDeliveryLineResponse,
    ErpOperatorCreateRequest,
    ErpOperatorPatchRequest,
    ErpOperatorResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_operator_service import (
    ErpOperatorConflictError,
    ErpOperatorError,
    ErpOperatorNotFoundError,
    create_erp_operator,
    create_erp_operator_line,
    disable_erp_operator,
    disable_erp_operator_line,
    list_erp_operator_lines,
    list_erp_operators,
    update_erp_operator,
    update_erp_operator_line,
)

router = APIRouter(prefix="/erp/operators", tags=["erp-operators"])


def _api_error(exc: ErpOperatorError) -> HTTPException:
    if isinstance(exc, ErpOperatorNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ErpOperatorConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[ErpOperatorResponse])
async def get_operators(
    include_inactive: bool = False,
    search: str | None = None,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpOperatorResponse]:
    return await list_erp_operators(
        session,
        include_inactive=include_inactive,
        search=search,
    )


@router.post("", response_model=ErpOperatorResponse, status_code=status.HTTP_201_CREATED)
async def post_operator(
    payload: ErpOperatorCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpOperatorResponse:
    try:
        return await create_erp_operator(session, request=payload, actor_user_id=auth.user.id)
    except ErpOperatorError as exc:
        raise _api_error(exc) from exc


@router.patch("/{operator_id}", response_model=ErpOperatorResponse)
async def patch_operator(
    operator_id: str,
    payload: ErpOperatorPatchRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpOperatorResponse:
    try:
        return await update_erp_operator(
            session,
            operator_id=operator_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except ErpOperatorError as exc:
        raise _api_error(exc) from exc


@router.post("/{operator_id}/disable", response_model=ErpOperatorResponse)
async def post_disable_operator(
    operator_id: str,
    row_version: int | None = None,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpOperatorResponse:
    try:
        return await disable_erp_operator(
            session,
            operator_id=operator_id,
            row_version=row_version,
            actor_user_id=auth.user.id,
        )
    except ErpOperatorError as exc:
        raise _api_error(exc) from exc


@router.get("/{operator_id}/lines", response_model=list[ErpDeliveryLineResponse])
async def get_operator_lines(
    operator_id: str,
    include_inactive: bool = False,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpDeliveryLineResponse]:
    try:
        return await list_erp_operator_lines(
            session,
            operator_id=operator_id,
            include_inactive=include_inactive,
        )
    except ErpOperatorError as exc:
        raise _api_error(exc) from exc


@router.post(
    "/{operator_id}/lines",
    response_model=ErpDeliveryLineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_operator_line(
    operator_id: str,
    payload: ErpDeliveryLineCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDeliveryLineResponse:
    try:
        return await create_erp_operator_line(
            session,
            operator_id=operator_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except ErpOperatorError as exc:
        raise _api_error(exc) from exc


@router.patch("/lines/{line_id}", response_model=ErpDeliveryLineResponse)
async def patch_operator_line(
    line_id: str,
    payload: ErpDeliveryLinePatchRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDeliveryLineResponse:
    try:
        return await update_erp_operator_line(
            session,
            line_id=line_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except ErpOperatorError as exc:
        raise _api_error(exc) from exc


@router.post("/lines/{line_id}/disable", response_model=ErpDeliveryLineResponse)
async def post_disable_operator_line(
    line_id: str,
    row_version: int | None = None,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDeliveryLineResponse:
    try:
        return await disable_erp_operator_line(
            session,
            line_id=line_id,
            row_version=row_version,
            actor_user_id=auth.user.id,
        )
    except ErpOperatorError as exc:
        raise _api_error(exc) from exc

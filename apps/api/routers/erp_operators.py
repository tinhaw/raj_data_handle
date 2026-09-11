"""Local ERP delivery-company and delivery-line APIs.

The endpoints deliberately contain no calls to ERP, RajWin or RajLuck remote
systems. They become operational only after the separately gated schema
migration has been run in an approved environment.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_erp_permission
from packages.common.database import get_db_session
from packages.domain.schemas.erp_operator import (
    ErpDeliveryLineCreateRequest,
    ErpDeliveryLinePatchRequest,
    ErpDeliveryLineResponse,
    ErpOperatorCreateRequest,
    ErpOperatorDeleteImpactResponse,
    ErpOperatorDeleteRequest,
    ErpOperatorPatchRequest,
    ErpOperatorResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_OPERATOR_MANAGE,
    ERP_PERMISSION_OPERATOR_VIEW,
    ErpScopePermissionError,
    assert_erp_operator_scope,
    resolve_erp_operator_scope,
)
from packages.domain.services.erp_operator_service import (
    ErpOperatorConflictError,
    ErpOperatorError,
    ErpOperatorNotFoundError,
    create_erp_operator,
    create_erp_operator_line,
    delete_erp_operator,
    disable_erp_operator,
    disable_erp_operator_line,
    get_erp_operator_delete_impact,
    get_erp_operator_line,
    list_erp_operator_lines,
    list_erp_operators,
    update_erp_operator,
    update_erp_operator_line,
)

router = APIRouter(prefix="/erp/operators", tags=["erp-operators"])


def _api_error(exc: ErpOperatorError | ErpScopePermissionError) -> HTTPException:
    if isinstance(exc, ErpScopePermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ErpOperatorNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ErpOperatorConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[ErpOperatorResponse])
async def get_operators(
    include_inactive: bool = False,
    search: str | None = None,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpOperatorResponse]:
    return await list_erp_operators(
        session,
        include_inactive=include_inactive,
        search=search,
        operator_ids=await resolve_erp_operator_scope(session, user_id=auth.user.id),
    )


@router.post("", response_model=ErpOperatorResponse, status_code=status.HTTP_201_CREATED)
async def post_operator(
    payload: ErpOperatorCreateRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpOperatorResponse:
    try:
        if await resolve_erp_operator_scope(session, user_id=auth.user.id) is not None:
            raise ErpScopePermissionError("仅拥有全部投放公司范围的用户可以新建公司。")
        return await create_erp_operator(session, request=payload, actor_user_id=auth.user.id)
    except (ErpOperatorError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.patch("/{operator_id}", response_model=ErpOperatorResponse)
async def patch_operator(
    operator_id: str,
    payload: ErpOperatorPatchRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpOperatorResponse:
    try:
        await assert_erp_operator_scope(session, user_id=auth.user.id, operator_id=operator_id)
        return await update_erp_operator(
            session,
            operator_id=operator_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except (ErpOperatorError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.post("/{operator_id}/disable", response_model=ErpOperatorResponse)
async def post_disable_operator(
    operator_id: str,
    row_version: int | None = None,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpOperatorResponse:
    try:
        await assert_erp_operator_scope(session, user_id=auth.user.id, operator_id=operator_id)
        return await disable_erp_operator(
            session,
            operator_id=operator_id,
            row_version=row_version,
            actor_user_id=auth.user.id,
        )
    except (ErpOperatorError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.get("/{operator_id}/delete-impact", response_model=ErpOperatorDeleteImpactResponse)
async def get_operator_delete_impact(
    operator_id: str,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpOperatorDeleteImpactResponse:
    try:
        await assert_erp_operator_scope(session, user_id=auth.user.id, operator_id=operator_id)
        return await get_erp_operator_delete_impact(session, operator_id=operator_id)
    except (ErpOperatorError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.delete("/{operator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_operator(
    operator_id: str,
    payload: ErpOperatorDeleteRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    try:
        await assert_erp_operator_scope(session, user_id=auth.user.id, operator_id=operator_id)
        await delete_erp_operator(
            session,
            operator_id=operator_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except (ErpOperatorError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.get("/{operator_id}/lines", response_model=list[ErpDeliveryLineResponse])
async def get_operator_lines(
    operator_id: str,
    include_inactive: bool = False,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpDeliveryLineResponse]:
    try:
        await assert_erp_operator_scope(session, user_id=auth.user.id, operator_id=operator_id)
        return await list_erp_operator_lines(
            session,
            operator_id=operator_id,
            include_inactive=include_inactive,
        )
    except (ErpOperatorError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.post(
    "/{operator_id}/lines",
    response_model=ErpDeliveryLineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_operator_line(
    operator_id: str,
    payload: ErpDeliveryLineCreateRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDeliveryLineResponse:
    try:
        await assert_erp_operator_scope(session, user_id=auth.user.id, operator_id=operator_id)
        return await create_erp_operator_line(
            session,
            operator_id=operator_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except (ErpOperatorError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.patch("/lines/{line_id}", response_model=ErpDeliveryLineResponse)
async def patch_operator_line(
    line_id: str,
    payload: ErpDeliveryLinePatchRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDeliveryLineResponse:
    try:
        line = await get_erp_operator_line(session, line_id=line_id)
        await assert_erp_operator_scope(
            session, user_id=auth.user.id, operator_id=line.operator_id
        )
        return await update_erp_operator_line(
            session,
            line_id=line_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except (ErpOperatorError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.post("/lines/{line_id}/disable", response_model=ErpDeliveryLineResponse)
async def post_disable_operator_line(
    line_id: str,
    row_version: int | None = None,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_OPERATOR_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDeliveryLineResponse:
    try:
        line = await get_erp_operator_line(session, line_id=line_id)
        await assert_erp_operator_scope(
            session, user_id=auth.user.id, operator_id=line.operator_id
        )
        return await disable_erp_operator_line(
            session,
            line_id=line_id,
            row_version=row_version,
            actor_user_id=auth.user.id,
        )
    except (ErpOperatorError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc

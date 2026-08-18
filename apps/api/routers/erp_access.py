"""Administrative APIs for local ERP roles and delivery-company scopes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_erp_permission
from packages.common.database import get_db_session
from packages.domain.schemas.erp_access import (
    ErpEffectiveAccessResponse,
    ErpRoleDefinition,
    ErpUserAccessResponse,
    ErpUserAccessUpdateRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_ACCESS_MANAGE,
    ErpAccessError,
    ErpAccessNotFoundError,
    get_erp_access_snapshot,
    role_definitions,
    update_erp_access,
)

router = APIRouter(prefix="/erp/access", tags=["erp-access"])


def _response(user_id: int, snapshot: object) -> ErpUserAccessResponse:
    return ErpUserAccessResponse(
        user_id=user_id,
        role_grants=snapshot.role_grants,
        all_operators=snapshot.all_operators,
        operator_ids=snapshot.operator_ids,
        effective_permissions=sorted(snapshot.effective_permissions),
    )


@router.get("/roles", response_model=list[ErpRoleDefinition])
async def get_roles(
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_ACCESS_MANAGE)),
) -> list[ErpRoleDefinition]:
    return [ErpRoleDefinition(**definition) for definition in role_definitions()]


@router.get("/me", response_model=ErpEffectiveAccessResponse)
async def get_my_access(
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ErpEffectiveAccessResponse:
    snapshot = await get_erp_access_snapshot(session, user_id=auth.user.id)
    return ErpEffectiveAccessResponse(
        role_grants=snapshot.role_grants,
        all_operators=snapshot.all_operators,
        operator_ids=snapshot.operator_ids,
        effective_permissions=sorted(snapshot.effective_permissions),
    )


@router.get("/users/{user_id}", response_model=ErpUserAccessResponse)
async def get_user_access(
    user_id: int,
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_ACCESS_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpUserAccessResponse:
    try:
        return _response(user_id, await get_erp_access_snapshot(session, user_id=user_id))
    except ErpAccessNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/users/{user_id}", response_model=ErpUserAccessResponse)
async def put_user_access(
    user_id: int,
    payload: ErpUserAccessUpdateRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_ACCESS_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpUserAccessResponse:
    try:
        snapshot = await update_erp_access(
            session,
            user_id=user_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except ErpAccessNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ErpAccessError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _response(user_id, snapshot)

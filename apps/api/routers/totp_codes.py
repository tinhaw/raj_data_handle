"""Admin-only management and non-cacheable projection of standalone TOTP accounts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_admin
from packages.common.database import get_db_session
from packages.domain.models import TotpAccount
from packages.domain.schemas.totp_code import (
    TotpAccountCreateRequest,
    TotpAccountPatchRequest,
    TotpAccountResponse,
    TotpCodeItemResponse,
    TotpCodeListResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.totp_code_service import (
    TotpAccountError,
    TotpAccountNotFoundError,
    create_totp_account,
    delete_totp_account,
    generate_totp_codes,
    list_totp_accounts,
    update_totp_account,
)

router = APIRouter(prefix="/settings", tags=["totp-codes"])


def _account_response(account: TotpAccount) -> TotpAccountResponse:
    return TotpAccountResponse.model_validate(account)


@router.get("/totp-accounts", response_model=list[TotpAccountResponse])
async def get_totp_accounts(
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[TotpAccountResponse]:
    return [_account_response(account) for account in await list_totp_accounts(session)]


@router.post(
    "/totp-accounts",
    response_model=TotpAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_totp_account(
    payload: TotpAccountCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> TotpAccountResponse:
    try:
        account = await create_totp_account(
            session,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except TotpAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _account_response(account)


@router.patch("/totp-accounts/{account_id}", response_model=TotpAccountResponse)
async def patch_totp_account(
    account_id: str,
    payload: TotpAccountPatchRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> TotpAccountResponse:
    try:
        account = await update_totp_account(
            session,
            account_id=account_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except TotpAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TotpAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _account_response(account)


@router.delete("/totp-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_totp_account(
    account_id: str,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    try:
        await delete_totp_account(
            session,
            account_id=account_id,
            actor_user_id=auth.user.id,
        )
    except TotpAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/totp-codes/generate", response_model=TotpCodeListResponse)
async def post_totp_codes(
    response: Response,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> TotpCodeListResponse:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    snapshot = await generate_totp_codes(session, actor_user_id=auth.user.id)
    return TotpCodeListResponse(
        generated_at=snapshot.generated_at,
        expires_at=snapshot.expires_at,
        period_seconds=snapshot.period_seconds,
        items=[TotpCodeItemResponse.model_validate(item) for item in snapshot.items],
    )

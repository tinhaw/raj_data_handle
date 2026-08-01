from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_admin
from packages.common.database import get_db_session
from packages.domain.models import SourceConfig
from packages.domain.schemas.source import (
    SourceConnectionTestResponse,
    SourceCreateRequest,
    SourceOrderRequest,
    SourcePatchRequest,
    SourceResponse,
    SourceUpsertRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.source_service import (
    SourceConflictError,
    SourceNotFoundError,
    SourceValidationError,
    clear_credentials,
    create_source,
    delete_source,
    list_sources,
    reorder_sources,
    upsert_source,
)
from packages.domain.services.source_service import (
    test_source_connection as run_source_connection_test,
)

router = APIRouter(tags=["sources"])


def _source_response(source: SourceConfig) -> SourceResponse:
    return SourceResponse(
        source_id=source.source_id,
        display_name=source.display_name,
        display_order=source.display_order,
        base_url=source.base_url,
        enabled=source.enabled,
        business_timezone=source.business_timezone,
        currency=source.currency,
        config_version=source.config_version,
        credential_configured=bool(source.encrypted_credentials),
        credential_updated_at=source.credential_updated_at,
        last_tested_at=source.last_tested_at,
        last_test_status=source.last_test_status,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


@router.get("/sources", response_model=list[SourceResponse])
async def enabled_sources(
    enabled: bool | None = True,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[SourceResponse]:
    return [_source_response(item) for item in await list_sources(session, enabled)]


@router.get("/settings/sources", response_model=list[SourceResponse])
async def settings_sources(
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[SourceResponse]:
    return [_source_response(item) for item in await list_sources(session)]


@router.post(
    "/settings/sources",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_source(
    payload: SourceCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> SourceResponse:
    try:
        source = await create_source(
            session,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except SourceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _source_response(source)


@router.put("/settings/sources/order", response_model=list[SourceResponse])
async def put_source_order(
    payload: SourceOrderRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[SourceResponse]:
    try:
        sources = await reorder_sources(
            session,
            source_ids=payload.source_ids,
            actor_user_id=auth.user.id,
        )
    except SourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [_source_response(source) for source in sources]


@router.put("/settings/sources/{source_id}", response_model=SourceResponse)
async def put_source(
    source_id: str,
    payload: SourceUpsertRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> SourceResponse:
    try:
        source = await upsert_source(
            session,
            source_id=source_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except SourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _source_response(source)


@router.patch("/settings/sources/{source_id}", response_model=SourceResponse)
async def patch_source(
    source_id: str,
    payload: SourcePatchRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> SourceResponse:
    try:
        source = await upsert_source(
            session,
            source_id=source_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except SourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _source_response(source)


@router.delete(
    "/settings/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_source(
    source_id: str,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    try:
        await delete_source(
            session,
            source_id=source_id,
            actor_user_id=auth.user.id,
        )
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SourceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/settings/sources/{source_id}/credentials", response_model=SourceResponse)
async def delete_source_credentials(
    source_id: str,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> SourceResponse:
    try:
        source = await clear_credentials(
            session,
            source_id=source_id,
            actor_user_id=auth.user.id,
        )
    except SourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _source_response(source)


@router.post(
    "/settings/sources/{source_id}/test-connection",
    response_model=SourceConnectionTestResponse,
)
async def test_source_connection(
    source_id: str,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> SourceConnectionTestResponse:
    try:
        source, request_id = await run_source_connection_test(
            session,
            source_id=source_id,
            actor_user_id=auth.user.id,
        )
    except SourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SourceConnectionTestResponse(
        source_id=source.source_id,
        status=source.last_test_status or "failed",
        request_id=request_id,
        message=(
            "连接成功，已同步支付渠道名称字典和可识别的充值渠道。"
            if source.last_test_status == "passed"
            else "连接失败，请检查 Base URL、账号、密码、TOTP Secret 和远端网络。"
        ),
    )

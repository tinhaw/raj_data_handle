from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_admin
from packages.common.database import get_db_session
from packages.common.settings import get_settings
from packages.domain.schemas.auth import (
    AuthUserResponse,
    CaptchaResponse,
    LoginRequest,
    LogoutResponse,
    UserAccessLogRequest,
    UserCreateRequest,
    UserLogQueryRequest,
    UserLogQueryResponse,
    UserLogResponse,
    UserResponse,
    UserUpdateRequest,
)
from packages.domain.services.auth_service import (
    AuthContext,
    AuthError,
    authenticate_user,
    create_user,
    list_users,
    query_user_logs,
    record_page_access,
    revoke_session,
    update_user,
)
from packages.domain.services.captcha_service import create_captcha, verify_captcha
from packages.domain.services.rate_limit_service import (
    LoginRateLimitExceeded,
    LoginRateLimitUnavailable,
    check_login_rate_limit,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_response(auth: AuthContext) -> AuthUserResponse:
    return AuthUserResponse(
        id=auth.user.id,
        username=auth.user.username,
        display_name=auth.user.display_name,
        role=auth.user.role,
        expires_at=auth.expires_at,
    )


@router.get("/captcha", response_model=CaptchaResponse)
async def captcha() -> CaptchaResponse:
    captcha_id, image, expires_at = create_captcha()
    return CaptchaResponse(captcha_id=captcha_id, image=image, expires_at=expires_at)


@router.post("/login", response_model=AuthUserResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> AuthUserResponse:
    client_ip = request.client.host if request.client else "unknown"
    try:
        await check_login_rate_limit(client_ip=client_ip, username=payload.username)
    except LoginRateLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except LoginRateLimitUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    if not verify_captcha(payload.captcha_id, payload.captcha_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期，请刷新后重试。",
        )
    try:
        auth, token = await authenticate_user(
            session,
            username=payload.username,
            password=payload.password,
            client_ip=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age=max(1, int((auth.expires_at - datetime.now(UTC)).total_seconds())),
        path="/",
    )
    return _auth_response(auth)


@router.get("/me", response_model=AuthUserResponse)
async def me(auth: AuthContext = Depends(get_auth_context)) -> AuthUserResponse:
    return _auth_response(auth)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> LogoutResponse:
    await revoke_session(session, auth_session=auth.session, actor_user_id=auth.user.id)
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )
    return LogoutResponse()


@router.post("/user-logs/access", status_code=status.HTTP_204_NO_CONTENT)
async def log_page_access(
    payload: UserAccessLogRequest,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await record_page_access(session, actor_user_id=auth.user.id, path=payload.path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/user-logs/query", response_model=UserLogQueryResponse)
async def user_logs(
    payload: UserLogQueryRequest,
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> UserLogQueryResponse:
    result = await query_user_logs(session, request=payload)
    return UserLogQueryResponse(
        items=[
            UserLogResponse(
                id=item.id,
                user_id=item.user_id,
                username=item.username,
                display_name=item.display_name,
                event_type=item.event_type,
                path=item.path,
                occurred_at=item.occurred_at,
            )
            for item in result.items
        ],
        total=result.total,
        page=payload.page,
        page_size=payload.page_size,
    )


@router.get("/users", response_model=list[UserResponse])
async def users(
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[UserResponse]:
    return [UserResponse.model_validate(user) for user in await list_users(session)]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def add_user(
    payload: UserCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    try:
        user = await create_user(
            session,
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
            role=payload.role,
            actor_user_id=auth.user.id,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserResponse.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def edit_user(
    user_id: int,
    payload: UserUpdateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    try:
        user = await update_user(
            session,
            user_id=user_id,
            actor_user_id=auth.user.id,
            display_name=payload.display_name,
            role=payload.role,
            is_active=payload.is_active,
            password=payload.password,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserResponse.model_validate(user)

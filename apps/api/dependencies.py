from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.database import get_db_session
from packages.common.settings import get_settings
from packages.domain.services.auth_service import AuthContext, AuthError, validate_session
from packages.storage import LocalFileStorage


async def get_auth_context(
    session: AsyncSession = Depends(get_db_session),
    session_cookie: str | None = Cookie(
        default=None,
        alias=get_settings().session_cookie_name,
    ),
) -> AuthContext:
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录。",
        )
    try:
        return await validate_session(session, session_cookie)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


async def require_admin(
    auth: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    if auth.user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可执行此操作。",
        )
    return auth


def get_file_storage(request: Request) -> LocalFileStorage:
    return request.app.state.file_storage

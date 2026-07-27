from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import (
    SecurityValidationError,
    create_session_jwt,
    decode_session_jwt,
    hash_password,
    new_session_secret,
    normalize_username,
    optional_fingerprint,
    session_expiry,
    sha256_text,
    verify_password,
)
from packages.common.settings import Settings, get_settings
from packages.domain.models import AppUser, AuthSession, SecurityAuditLog

ALLOWED_ROLES = {"admin", "user"}
ADMIN_ROLE = "admin"


class AuthError(ValueError):
    pass


@dataclass(slots=True)
class AuthContext:
    user: AppUser
    session: AuthSession
    expires_at: datetime


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def write_audit(
    session: AsyncSession,
    *,
    action: str,
    actor_user_id: int | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    result: str = "success",
    metadata: dict[str, object] | None = None,
) -> None:
    session.add(
        SecurityAuditLog(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            metadata_json=metadata or {},
        )
    )


async def authenticate_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    client_ip: str | None,
    user_agent: str | None,
    settings: Settings | None = None,
) -> tuple[AuthContext, str]:
    current_settings = settings or get_settings()
    normalized = normalize_username(username)
    user = await session.scalar(select(AppUser).where(AppUser.username_normalized == normalized))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        await write_audit(
            session,
            action="login",
            result="failure",
            metadata={"username_hash": sha256_text(normalized)},
        )
        await session.commit()
        raise AuthError("用户名或密码错误。")

    secret = new_session_secret()
    expires_at = session_expiry(current_settings)
    auth_session = AuthSession(
        token_hash=sha256_text(secret),
        user_id=user.id,
        expires_at=expires_at,
        client_ip_hash=optional_fingerprint(client_ip),
        user_agent_hash=optional_fingerprint(user_agent),
    )
    session.add(auth_session)
    user.last_login_at = datetime.now(UTC)
    await write_audit(
        session,
        action="login",
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
    )
    await session.commit()
    token = create_session_jwt(
        user_id=user.id,
        role=user.role,
        session_secret=secret,
        expires_at=expires_at,
        settings=current_settings,
    )
    return AuthContext(user=user, session=auth_session, expires_at=expires_at), token


async def validate_session(
    session: AsyncSession,
    token: str,
    settings: Settings | None = None,
) -> AuthContext:
    try:
        payload = decode_session_jwt(token, settings)
        user_id = int(payload["sub"])
        secret = str(payload["sid"])
    except (SecurityValidationError, KeyError, TypeError, ValueError) as exc:
        raise AuthError("登录会话无效或已过期。") from exc

    auth_session = await session.scalar(
        select(AuthSession).where(AuthSession.token_hash == sha256_text(secret))
    )
    now = datetime.now(UTC)
    if (
        auth_session is None
        or auth_session.user_id != user_id
        or auth_session.revoked_at is not None
        or _aware(auth_session.expires_at) <= now
    ):
        raise AuthError("登录会话无效或已过期。")
    user = await session.get(AppUser, user_id)
    if user is None or not user.is_active:
        raise AuthError("账号不存在或已停用。")
    auth_session.last_seen_at = now
    return AuthContext(user=user, session=auth_session, expires_at=_aware(auth_session.expires_at))


async def revoke_session(
    session: AsyncSession,
    *,
    auth_session: AuthSession,
    actor_user_id: int,
) -> None:
    if auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now(UTC)
    await write_audit(
        session,
        action="logout",
        actor_user_id=actor_user_id,
        target_type="session",
        target_id=auth_session.id,
    )
    await session.commit()


async def list_users(session: AsyncSession) -> list[AppUser]:
    result = await session.scalars(select(AppUser).order_by(AppUser.created_at.asc()))
    return list(result)


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    display_name: str,
    role: str,
    actor_user_id: int | None,
) -> AppUser:
    normalized = normalize_username(username)
    if not normalized:
        raise AuthError("用户名不能为空。")
    if role not in ALLOWED_ROLES:
        raise AuthError("角色只能是 admin 或 user。")
    if await session.scalar(select(AppUser.id).where(AppUser.username_normalized == normalized)):
        raise AuthError("用户名已存在。")
    try:
        password_hash = hash_password(password)
    except SecurityValidationError as exc:
        raise AuthError(str(exc)) from exc
    user = AppUser(
        username=username.strip(),
        username_normalized=normalized,
        password_hash=password_hash,
        display_name=display_name.strip() or username.strip(),
        role=role,
    )
    session.add(user)
    await session.flush()
    await write_audit(
        session,
        action="user.create",
        actor_user_id=actor_user_id,
        target_type="user",
        target_id=str(user.id),
        metadata={"role": role},
    )
    await session.commit()
    return user


async def update_user(
    session: AsyncSession,
    *,
    user_id: int,
    actor_user_id: int,
    display_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> AppUser:
    user = await session.get(AppUser, user_id)
    if user is None:
        raise AuthError("用户不存在。")
    if role is not None and role not in ALLOWED_ROLES:
        raise AuthError("角色只能是 admin 或 user。")

    removing_admin = user.role == ADMIN_ROLE and (role == "user" or is_active is False)
    if removing_admin:
        active_admins = await session.scalar(
            select(func.count())
            .select_from(AppUser)
            .where(AppUser.role == ADMIN_ROLE, AppUser.is_active.is_(True))
        )
        if (active_admins or 0) <= 1:
            raise AuthError("不能停用或降级最后一个有效管理员。")

    changed_fields: list[str] = []
    if display_name is not None:
        user.display_name = display_name.strip()
        changed_fields.append("display_name")
    if role is not None:
        user.role = role
        changed_fields.append("role")
    if is_active is not None:
        user.is_active = is_active
        changed_fields.append("is_active")
    if password is not None:
        try:
            user.password_hash = hash_password(password)
        except SecurityValidationError as exc:
            raise AuthError(str(exc)) from exc
        user.password_changed_at = datetime.now(UTC)
        changed_fields.append("password")

    if {"role", "is_active", "password"} & set(changed_fields):
        await session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    await write_audit(
        session,
        action="user.update",
        actor_user_id=actor_user_id,
        target_type="user",
        target_id=str(user.id),
        metadata={"changed_fields": changed_fields},
    )
    await session.commit()
    return user

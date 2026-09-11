"""ERP domain roles, permissions and delivery-company access scopes.

The grants here never change ``AppUser.role``: global roles remain responsible
for login and platform administration, while ERP roles govern local ERP work.
Every ERP endpoint must enforce one of these permissions. Application admins
receive the complete set, while ordinary users remain constrained by both
their ERP roles and their delivery-company scope.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    AppUser,
    ErpOperator,
    ErpUserAccessProfile,
    ErpUserOperatorScope,
    ErpUserRoleGrant,
)
from packages.domain.schemas.erp_access import ErpUserAccessUpdateRequest
from packages.domain.services.auth_service import write_audit

ERP_PERMISSION_WORKSPACE_VIEW = "ERP_WORKSPACE_VIEW"
ERP_PERMISSION_OPERATOR_VIEW = "ERP_OPERATOR_VIEW"
ERP_PERMISSION_OPERATOR_MANAGE = "ERP_OPERATOR_MANAGE"
ERP_PERMISSION_LEDGER_VIEW = "ERP_LEDGER_VIEW"
ERP_PERMISSION_LEDGER_WRITE = "ERP_LEDGER_WRITE"
ERP_PERMISSION_LEDGER_OVERRIDE = "ERP_LEDGER_OVERRIDE"
ERP_PERMISSION_LEDGER_CONFIRM = "ERP_LEDGER_CONFIRM"
ERP_PERMISSION_LEDGER_REOPEN = "ERP_LEDGER_REOPEN"
ERP_PERMISSION_PERIOD_LOCK = "ERP_PERIOD_LOCK"
ERP_PERMISSION_IMPORT = "ERP_IMPORT"
ERP_PERMISSION_REPORT_VIEW = "ERP_REPORT_VIEW"
ERP_PERMISSION_REPORT_EXPORT = "ERP_REPORT_EXPORT"
ERP_PERMISSION_AUDIT_VIEW = "ERP_AUDIT_VIEW"
ERP_PERMISSION_REDEMPTION_VIEW = "ERP_REDEMPTION_VIEW"
ERP_PERMISSION_REDEMPTION_MANAGE = "ERP_REDEMPTION_MANAGE"
ERP_PERMISSION_REDEMPTION_GENERATE = "ERP_REDEMPTION_GENERATE"
ERP_PERMISSION_REDEMPTION_EXPORT = "ERP_REDEMPTION_EXPORT"
ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE = "ERP_REMOTE_ACCOUNT_MANAGE"
ERP_PERMISSION_ACCESS_MANAGE = "ERP_ACCESS_MANAGE"

ERP_ROLES: dict[str, tuple[str, frozenset[str]]] = {
    "ERP_VIEWER": (
        "只读查看员",
        frozenset(
            {
                ERP_PERMISSION_WORKSPACE_VIEW,
                ERP_PERMISSION_OPERATOR_VIEW,
                ERP_PERMISSION_LEDGER_VIEW,
                ERP_PERMISSION_REPORT_VIEW,
            }
        ),
    ),
    "ERP_LEDGER_OPERATOR": (
        "台账录入员",
        frozenset(
            {
                ERP_PERMISSION_WORKSPACE_VIEW,
                ERP_PERMISSION_OPERATOR_VIEW,
                ERP_PERMISSION_LEDGER_VIEW,
                ERP_PERMISSION_LEDGER_WRITE,
                ERP_PERMISSION_IMPORT,
                ERP_PERMISSION_REPORT_VIEW,
            }
        ),
    ),
    "ERP_FINANCE_ADMIN": (
        "财务管理员",
        frozenset(
            {
                ERP_PERMISSION_WORKSPACE_VIEW,
                ERP_PERMISSION_OPERATOR_VIEW,
                ERP_PERMISSION_OPERATOR_MANAGE,
                ERP_PERMISSION_LEDGER_VIEW,
                ERP_PERMISSION_LEDGER_WRITE,
                ERP_PERMISSION_LEDGER_OVERRIDE,
                ERP_PERMISSION_LEDGER_CONFIRM,
                ERP_PERMISSION_LEDGER_REOPEN,
                ERP_PERMISSION_PERIOD_LOCK,
                ERP_PERMISSION_IMPORT,
                ERP_PERMISSION_REPORT_VIEW,
                ERP_PERMISSION_REPORT_EXPORT,
            }
        ),
    ),
    "ERP_AUDITOR": (
        "审计员",
        frozenset(
            {
                ERP_PERMISSION_WORKSPACE_VIEW,
                ERP_PERMISSION_OPERATOR_VIEW,
                ERP_PERMISSION_LEDGER_VIEW,
                ERP_PERMISSION_REPORT_VIEW,
                ERP_PERMISSION_REPORT_EXPORT,
                ERP_PERMISSION_AUDIT_VIEW,
            }
        ),
    ),
    "ERP_REDEMPTION_MANAGER": (
        "兑换码管理员",
        frozenset(
            {
                ERP_PERMISSION_WORKSPACE_VIEW,
                ERP_PERMISSION_REDEMPTION_VIEW,
                ERP_PERMISSION_REDEMPTION_MANAGE,
                ERP_PERMISSION_REDEMPTION_GENERATE,
                ERP_PERMISSION_REDEMPTION_EXPORT,
            }
        ),
    ),
    "ERP_SYSTEM_ADMIN": (
        "ERP 系统管理员",
        frozenset(
            {
                ERP_PERMISSION_WORKSPACE_VIEW,
                ERP_PERMISSION_OPERATOR_VIEW,
                ERP_PERMISSION_OPERATOR_MANAGE,
                ERP_PERMISSION_LEDGER_VIEW,
                ERP_PERMISSION_LEDGER_WRITE,
                ERP_PERMISSION_LEDGER_OVERRIDE,
                ERP_PERMISSION_LEDGER_CONFIRM,
                ERP_PERMISSION_LEDGER_REOPEN,
                ERP_PERMISSION_PERIOD_LOCK,
                ERP_PERMISSION_IMPORT,
                ERP_PERMISSION_REPORT_VIEW,
                ERP_PERMISSION_REPORT_EXPORT,
                ERP_PERMISSION_AUDIT_VIEW,
                ERP_PERMISSION_REDEMPTION_VIEW,
                ERP_PERMISSION_REDEMPTION_MANAGE,
                ERP_PERMISSION_REDEMPTION_GENERATE,
                ERP_PERMISSION_REDEMPTION_EXPORT,
                ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE,
                ERP_PERMISSION_ACCESS_MANAGE,
            }
        ),
    ),
}

ALL_ERP_PERMISSIONS = frozenset(
    permission for _, permissions in ERP_ROLES.values() for permission in permissions
)


class ErpAccessError(ValueError):
    pass


class ErpAccessNotFoundError(ErpAccessError):
    pass


class ErpAccessValidationError(ErpAccessError):
    pass


class ErpScopePermissionError(ErpAccessError):
    pass


@dataclass(frozen=True, slots=True)
class ErpAccessSnapshot:
    role_grants: list[str]
    all_operators: bool
    operator_ids: list[str]
    effective_permissions: frozenset[str]


def role_definitions() -> list[dict[str, object]]:
    return [
        {"code": code, "label": label, "permissions": sorted(permissions)}
        for code, (label, permissions) in ERP_ROLES.items()
    ]


async def _get_user(session: AsyncSession, user_id: int) -> AppUser:
    user = await session.get(AppUser, user_id)
    if user is None:
        raise ErpAccessNotFoundError("用户不存在。")
    return user


async def get_erp_access_snapshot(
    session: AsyncSession,
    *,
    user_id: int,
) -> ErpAccessSnapshot:
    user = await _get_user(session, user_id)
    if user.role == "admin":
        return ErpAccessSnapshot(
            role_grants=sorted(ERP_ROLES),
            all_operators=True,
            operator_ids=[],
            effective_permissions=ALL_ERP_PERMISSIONS,
        )

    role_grants = list(
        await session.scalars(
            select(ErpUserRoleGrant.role)
            .where(ErpUserRoleGrant.user_id == user_id)
            .order_by(ErpUserRoleGrant.role.asc())
        )
    )
    profile = await session.get(ErpUserAccessProfile, user_id)
    operator_ids = list(
        await session.scalars(
            select(ErpUserOperatorScope.operator_id)
            .where(ErpUserOperatorScope.user_id == user_id)
            .order_by(ErpUserOperatorScope.operator_id.asc())
        )
    )
    permissions = frozenset(
        permission
        for role in role_grants
        for permission in ERP_ROLES.get(role, ("", frozenset()))[1]
    )
    return ErpAccessSnapshot(
        role_grants=role_grants,
        all_operators=bool(profile and profile.all_operators),
        operator_ids=operator_ids,
        effective_permissions=permissions,
    )


async def update_erp_access(
    session: AsyncSession,
    *,
    user_id: int,
    request: ErpUserAccessUpdateRequest,
    actor_user_id: int,
) -> ErpAccessSnapshot:
    await _get_user(session, user_id)
    unknown_roles = set(request.role_grants) - set(ERP_ROLES)
    if unknown_roles:
        raise ErpAccessValidationError("包含不支持的 ERP 角色。")
    operator_ids = sorted(set(request.operator_ids))
    if operator_ids:
        existing_ids = set(
            await session.scalars(select(ErpOperator.id).where(ErpOperator.id.in_(operator_ids)))
        )
        if set(operator_ids) - existing_ids:
            raise ErpAccessValidationError("包含不存在的投放公司。")

    profile = await session.get(ErpUserAccessProfile, user_id)
    if profile is None:
        session.add(
            ErpUserAccessProfile(
                user_id=user_id,
                all_operators=request.all_operators,
                updated_by=actor_user_id,
            )
        )
    else:
        profile.all_operators = request.all_operators
        profile.updated_by = actor_user_id

    await session.execute(delete(ErpUserRoleGrant).where(ErpUserRoleGrant.user_id == user_id))
    await session.execute(
        delete(ErpUserOperatorScope).where(ErpUserOperatorScope.user_id == user_id)
    )
    session.add_all(
        [
            ErpUserRoleGrant(user_id=user_id, role=role, granted_by=actor_user_id)
            for role in sorted(request.role_grants)
        ]
    )
    if not request.all_operators:
        session.add_all(
            [
                ErpUserOperatorScope(
                    user_id=user_id,
                    operator_id=operator_id,
                    granted_by=actor_user_id,
                )
                for operator_id in operator_ids
            ]
        )
    await session.flush()
    await write_audit(
        session,
        action="erp_access.update",
        actor_user_id=actor_user_id,
        target_type="user",
        target_id=str(user_id),
        metadata={
            "role_grants": sorted(request.role_grants),
            "all_operators": request.all_operators,
            "operator_count": 0 if request.all_operators else len(operator_ids),
        },
    )
    await session.commit()
    return await get_erp_access_snapshot(session, user_id=user_id)


async def user_has_erp_permission(
    session: AsyncSession,
    *,
    user_id: int,
    permission: str,
    operator_id: str | None = None,
) -> bool:
    snapshot = await get_erp_access_snapshot(session, user_id=user_id)
    if permission not in snapshot.effective_permissions:
        return False
    return (
        operator_id is None
        or snapshot.all_operators
        or operator_id in set(snapshot.operator_ids)
    )


async def resolve_erp_operator_scope(
    session: AsyncSession,
    *,
    user_id: int,
    requested_operator_ids: list[str] | None = None,
) -> list[str] | None:
    """Return the safe operator filter for a request.

    ``None`` means all operators. A user with a restricted scope cannot widen
    it by supplying query parameters; an explicit out-of-scope id is rejected
    rather than silently omitted so the authorization failure is observable.
    """

    snapshot = await get_erp_access_snapshot(session, user_id=user_id)
    requested = sorted(set(requested_operator_ids or []))
    if snapshot.all_operators:
        return requested or None
    allowed = set(snapshot.operator_ids)
    if requested and not set(requested).issubset(allowed):
        raise ErpScopePermissionError("没有所选投放公司的数据权限。")
    return requested or sorted(allowed)


async def assert_erp_operator_scope(
    session: AsyncSession,
    *,
    user_id: int,
    operator_id: str,
) -> None:
    await resolve_erp_operator_scope(
        session,
        user_id=user_id,
        requested_operator_ids=[operator_id],
    )

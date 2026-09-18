from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from packages.common.schemas import ApiSchema

ErpRole = Literal[
    "ERP_VIEWER",
    "ERP_LEDGER_OPERATOR",
    "ERP_FINANCE_ADMIN",
    "ERP_AUDITOR",
    "ERP_REDEMPTION_MANAGER",
    "ERP_SYSTEM_ADMIN",
]


class ErpRoleDefinition(ApiSchema):
    code: ErpRole
    label: str
    permissions: list[str]


class ErpUserAccessResponse(ApiSchema):
    user_id: int
    role_grants: list[ErpRole]
    all_operators: bool
    operator_ids: list[str]
    effective_permissions: list[str]


class ErpUserAccessUpdateRequest(ApiSchema):
    role_grants: list[ErpRole] = Field(default_factory=list, max_length=6)
    all_operators: bool = False
    operator_ids: list[str] = Field(default_factory=list, max_length=2_000)

    @field_validator("role_grants", "operator_ids")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("不能包含重复项。")
        return value


class ErpEffectiveAccessResponse(ApiSchema):
    role_grants: list[ErpRole]
    all_operators: bool
    operator_ids: list[str]
    effective_permissions: list[str]


class ErpCompatibilitySessionResponse(ApiSchema):
    """Authenticated identity envelope consumed by the ERP compatibility service.

    It intentionally contains no password, session token, remote credential or
    legacy ERP user identifier. The caller must forward the existing
    ``raj_session`` cookie; the main API remains the only session authority.
    """

    user_id: int
    username: str
    display_name: str
    global_role: Literal["admin", "user"]
    expires_at: datetime
    role_grants: list[ErpRole]
    all_operators: bool
    operator_ids: list[int]
    effective_permissions: list[str]

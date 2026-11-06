"""Alembic autogenerate boundaries for migration-owned compatibility tables.

The imported Spring ERP runtime maps these tables with JPA.  Alembic owns
their DDL, but the FastAPI SQLAlchemy metadata deliberately does not duplicate
the same large model.  Autogenerate must therefore preserve the tables instead
of interpreting their absence from ``Base.metadata`` as a drop request.
"""

from __future__ import annotations

from typing import Any

ERP_COMPATIBILITY_TABLES = frozenset(
    {
        "erp_compat_operators",
        "erp_compat_operator_accounts",
        "erp_compat_daily_balances",
        "erp_compat_accounting_period_locks",
        "erp_compat_import_jobs",
        "erp_compat_import_job_rows",
        "erp_compat_audit_logs",
        "erp_compat_redemption_campaigns",
        "erp_compat_redemption_campaign_tiers",
        "erp_compat_redemption_code_tasks",
        "erp_compat_redemption_code_batches",
        "erp_compat_redemption_code_issues",
    }
)


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,  # noqa: ARG001 - Alembic callback contract
    compare_to: Any,  # noqa: ARG001 - Alembic callback contract
) -> bool:
    """Exclude only migration-owned ERP compatibility tables and children."""

    table_name = (
        name
        if type_ == "table"
        else getattr(getattr(object_, "table", None), "name", None)
    )
    return table_name not in ERP_COMPATIBILITY_TABLES

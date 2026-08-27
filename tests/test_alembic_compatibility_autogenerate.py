from __future__ import annotations

from types import SimpleNamespace

from database.migrations.autogenerate import ERP_COMPATIBILITY_TABLES, include_object
from deploy.rehearse_erp_snapshot import TABLE_RULES
from packages.domain.models import Base


def test_autogenerate_guard_covers_every_migration_owned_history_table() -> None:
    assert ERP_COMPATIBILITY_TABLES == {rule.target for rule in TABLE_RULES}


def test_autogenerate_ignores_compatibility_tables_and_their_indexes() -> None:
    table_name = "erp_compat_redemption_code_issues"
    index = SimpleNamespace(table=SimpleNamespace(name=table_name))

    assert include_object(object(), table_name, "table", True, None) is False
    assert include_object(index, "ix_erp_compat_issue", "index", True, None) is False


def test_autogenerate_keeps_canonical_tables_and_indexes_visible() -> None:
    index = SimpleNamespace(table=SimpleNamespace(name="remote_accounts"))

    assert include_object(object(), "remote_accounts", "table", True, None) is True
    assert include_object(index, "ix_remote_accounts_source_id", "index", True, None) is True


def test_orm_index_names_match_the_deployed_schema_contract() -> None:
    expected = {
        "remote_accounts": {"ix_remote_account_source_enabled"},
        "erp_operators": {"ix_erp_operator_name", "ix_erp_operator_status"},
        "erp_operator_lines": {"ix_erp_operator_line_operator_status"},
        "erp_daily_balances": {
            "ix_erp_daily_balance_line_date",
            "ix_erp_daily_balance_date_status",
        },
        "erp_accounting_period_locks": {"ix_erp_period_lock_month_status"},
        "erp_redemption_code_batches": {
            "ix_erp_redemption_batch_task_id",
            "ix_erp_redemption_batch_remote_account_id",
            "ix_erp_redemption_batch_source_id",
            "ix_erp_redemption_code_batches_campaign_id",
        },
        "erp_redemption_code_issues": {
            "ix_erp_redemption_issue_remote_workflow_status",
            "ix_erp_redemption_code_issues_campaign_id",
            "ix_erp_redemption_code_issues_campaign_tier_id",
            "ix_erp_redemption_code_issues_batch_id",
        },
        "erp_redemption_remote_executions": {
            "ix_erp_redemption_remote_execution_plan_requested",
            "ix_erp_redemption_remote_executions_plan_id",
            "ix_erp_redemption_remote_executions_issue_id",
            "ix_erp_redemption_remote_executions_status",
        },
    }

    for table_name, index_names in expected.items():
        assert {index.name for index in Base.metadata.tables[table_name].indexes} == index_names

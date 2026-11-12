"""Allow durable reward verification holds without changing shared identity or inventory."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_0058"
down_revision = "20261112_0057"
branch_labels = None
depends_on = None

ISSUES = "erp_compat_redemption_code_issues"
WORKFLOW = (
    "workflow_status in ('PENDING_CREATION', 'CREATING_REMOTE', 'CREATED', "
    "'PUBLISHED', 'CODE_IMPORTED', 'FAILED', 'REWARD_CHECK_REQUIRED', 'REWARD_CONFIRM_REQUIRED')"
)
REUSE = (
    "reused_from_issue_id IS NULL OR (reused_from_issue_id <> id AND remote_market_id > 0 AND "
    "remote_configuration_id IS NULL AND remote_create_receipt_id IS NULL "
    "AND remote_reference_id IS NULL "
    "AND redemption_code IS NULL AND remote_group_key IS NULL AND workflow_status IN "
    "('CREATED', 'REWARD_CHECK_REQUIRED', 'REWARD_CONFIRM_REQUIRED') AND state = 'PENDING')"
)


def upgrade() -> None:
    connection = op.get_bind()
    checks = sa.inspect(connection).get_check_constraints(ISSUES)
    targets = [check for check in checks if "workflow_status" in check["sqltext"].lower()]
    expected_counts = {1, 2} if connection.dialect.name == "sqlite" else {2}
    if len(targets) not in expected_counts or not any(
        check["name"] == "ck_erp_compat_issue_reuse" for check in targets
    ):
        raise RuntimeError(
            "Unexpected redemption workflow constraints; refusing to weaken other guards"
        )
    if connection.dialect.name == "sqlite":
        # Older SQLite batch migrations may omit the unnamed workflow check; restore it here.
        table = sa.Table(ISSUES, sa.MetaData(), autoload_with=connection)
        for constraint in list(table.constraints):
            if (
                isinstance(constraint, sa.CheckConstraint)
                and "workflow_status" in str(constraint.sqltext).lower()
            ):
                table.constraints.remove(constraint)
        with op.batch_alter_table(ISSUES, recreate="always", copy_from=table) as batch:
            batch.create_check_constraint("chk_redemption_issue_workflow_status", WORKFLOW)
            batch.create_check_constraint("ck_erp_compat_issue_reuse", REUSE)
    else:
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
        for check in targets:
            op.drop_constraint(check["name"], ISSUES, type_="check")
        op.create_check_constraint("chk_redemption_issue_workflow_status", ISSUES, WORKFLOW)
        op.create_check_constraint("ck_erp_compat_issue_reuse", ISSUES, REUSE)


def downgrade() -> None:
    raise RuntimeError("Reward verification states must be retained; use a compatible forward fix")

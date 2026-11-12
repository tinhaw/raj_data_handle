"""Let tasks reference a canonical configuration without duplicating code inventory."""

import sqlalchemy as sa
from alembic import op

revision = "20261111_0056"
down_revision = "20261106_0055"
branch_labels = None
depends_on = None

ISSUES = "erp_compat_redemption_code_issues"
CODES = "erp_compat_redemption_issue_codes"
FK = "fk_erp_compat_issue_reuse_market"
CHECK = "ck_erp_compat_issue_reuse"
INDEX = "ix_erp_compat_issue_reused_from"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
    with op.batch_alter_table(ISSUES) as batch:
        batch.add_column(sa.Column("reused_from_issue_id", sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            FK,
            ISSUES,
            ["reused_from_issue_id", "remote_market_id"],
            ["id", "remote_market_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            CHECK,
            "reused_from_issue_id IS NULL OR ("
            "reused_from_issue_id <> id AND remote_market_id > 0 AND "
            "remote_configuration_id IS NULL AND remote_create_receipt_id IS NULL AND "
            "remote_reference_id IS NULL AND redemption_code IS NULL AND remote_group_key IS NULL "
            "AND workflow_status = 'CREATED' AND state = 'PENDING')",
        )
        batch.create_index(INDEX, ["reused_from_issue_id"])
    if op.get_bind().dialect.name == "postgresql":
        # Lock the canonical row before linking. Prevent chains and changes of identity
        # while other tasks reference it; status and first code import remain mutable.
        op.execute(
            sa.text(f"""CREATE FUNCTION erp_compat_guard_redemption_reuse() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE owner_row {ISSUES}%ROWTYPE;
            BEGIN
                IF NEW.reused_from_issue_id IS NOT NULL THEN
                    SELECT * INTO owner_row FROM {ISSUES}
                        WHERE id = NEW.reused_from_issue_id FOR UPDATE;
                    IF NOT FOUND OR owner_row.reused_from_issue_id IS NOT NULL
                        OR owner_row.remote_configuration_id IS NULL
                        OR owner_row.remote_configuration_id IN ('-1', '0') THEN
                        RAISE EXCEPTION 'Reuse requires a canonical valid configuration';
                    END IF;
                    IF EXISTS (SELECT 1 FROM {CODES} WHERE issue_id = NEW.id) THEN
                        RAISE EXCEPTION 'A linked issue cannot own code inventory';
                    END IF;
                END IF;
                IF TG_OP = 'UPDATE' AND (
                    NEW.reused_from_issue_id IS DISTINCT FROM OLD.reused_from_issue_id
                    OR NEW.remote_configuration_id IS DISTINCT FROM OLD.remote_configuration_id
                    OR NEW.remote_market_id IS DISTINCT FROM OLD.remote_market_id)
                    AND EXISTS (SELECT 1 FROM {ISSUES} WHERE reused_from_issue_id = NEW.id) THEN
                    RAISE EXCEPTION 'A referenced configuration identity cannot be changed';
                END IF;
                RETURN NEW;
            END; $$""")
        )
        op.execute(
            sa.text(f"""CREATE TRIGGER trg_erp_compat_redemption_reuse
            BEFORE INSERT OR UPDATE ON {ISSUES}
            FOR EACH ROW EXECUTE FUNCTION erp_compat_guard_redemption_reuse()""")
        )
        op.execute(
            sa.text(f"""CREATE FUNCTION erp_compat_guard_reused_code_inventory()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                PERFORM 1 FROM {ISSUES} WHERE id = NEW.issue_id
                    AND reused_from_issue_id IS NULL FOR UPDATE;
                IF NOT FOUND THEN RAISE EXCEPTION 'Only a canonical issue can own codes'; END IF;
                RETURN NEW;
            END; $$""")
        )
        op.execute(
            sa.text(f"""CREATE TRIGGER trg_erp_compat_reused_code_inventory
            BEFORE INSERT OR UPDATE ON {CODES}
            FOR EACH ROW EXECUTE FUNCTION erp_compat_guard_reused_code_inventory()""")
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text(f"SELECT 1 FROM {ISSUES} WHERE reused_from_issue_id IS NOT NULL LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Reuse links exist. Retain this schema and use a forward fix.")
    if op.get_bind().dialect.name == "postgresql":
        for table, name in ((CODES, "reused_code_inventory"), (ISSUES, "redemption_reuse")):
            op.execute(sa.text(f"DROP TRIGGER trg_erp_compat_{name} ON {table}"))
            op.execute(sa.text(f"DROP FUNCTION erp_compat_guard_{name}()"))
    with op.batch_alter_table(ISSUES) as batch:
        batch.drop_index(INDEX)
        batch.drop_constraint(FK, type_="foreignkey")
        batch.drop_constraint(CHECK, type_="check")
        batch.drop_column("reused_from_issue_id")

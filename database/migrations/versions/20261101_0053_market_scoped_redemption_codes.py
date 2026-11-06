"""Keep code values unique within their market while preserving every code."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_0053"
down_revision = "20261101_0052"
branch_labels = None
depends_on = None

ISSUES = "erp_compat_redemption_code_issues"
CODES = "erp_compat_redemption_issue_codes"
OLD_ISSUE_UNIQUE = "uq_erp_compat_redemption_issue_code"
OLD_CODE_UNIQUE = "uq_erp_compat_redemption_issue_codes_code"
ISSUE_UNIQUE = "uq_erp_compat_issue_market_code"
CODE_UNIQUE = "uq_erp_compat_issue_codes_market_code"
PARENT_UNIQUE = "uq_erp_compat_issue_id_market"
MARKET_FK = "fk_erp_compat_issue_codes_market"
FUNCTION = "erp_compat_fill_redemption_code_market"
TRIGGER = "trg_erp_compat_redemption_code_market"


def upgrade() -> None:
    connection = op.get_bind()
    unresolved = connection.execute(
        sa.text(f"""SELECT 1 FROM {CODES} code LEFT JOIN {ISSUES} issue
            ON issue.id=code.issue_id WHERE issue.id IS NULL
            OR issue.remote_market_id IS NULL OR issue.remote_market_id<0 LIMIT 1""")
    ).first()
    if unresolved:
        raise RuntimeError("Code market provenance is unresolved; reconcile before migration.")
    op.add_column(CODES, sa.Column("remote_market_id", sa.BigInteger(), nullable=True))
    op.execute(
        sa.text(f"""UPDATE {CODES} SET remote_market_id=(
        SELECT issue.remote_market_id FROM {ISSUES} issue WHERE issue.id={CODES}.issue_id)""")
    )
    with op.batch_alter_table(ISSUES) as batch:
        batch.drop_constraint(OLD_ISSUE_UNIQUE, type_="unique")
        batch.create_unique_constraint(ISSUE_UNIQUE, ["remote_market_id", "redemption_code"])
        batch.create_unique_constraint(PARENT_UNIQUE, ["id", "remote_market_id"])
    with op.batch_alter_table(CODES) as batch:
        batch.alter_column("remote_market_id", existing_type=sa.BigInteger(), nullable=False)
        batch.drop_constraint(OLD_CODE_UNIQUE, type_="unique")
        batch.create_unique_constraint(CODE_UNIQUE, ["remote_market_id", "code"])
        batch.create_foreign_key(
            MARKET_FK,
            ISSUES,
            ["issue_id", "remote_market_id"],
            ["id", "remote_market_id"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            "ck_erp_compat_code_market_nonnegative", "remote_market_id >= 0"
        )
    if connection.dialect.name == "postgresql":
        # Older applications omit this new column. Fill it from the parent,
        # permitting application rollback without weakening market ownership.
        op.execute(
            sa.text(f"""CREATE FUNCTION {FUNCTION}() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE expected_market bigint;
            BEGIN
                SELECT remote_market_id INTO expected_market FROM {ISSUES} WHERE id=NEW.issue_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Redemption issue does not exist';
                END IF;
                IF NEW.remote_market_id IS NOT NULL AND NEW.remote_market_id <> expected_market THEN
                    RAISE EXCEPTION 'Redemption code market differs from its issue';
                END IF;
                NEW.remote_market_id := expected_market;
                RETURN NEW;
            END; $$""")
        )
        op.execute(
            sa.text(f"""CREATE TRIGGER {TRIGGER}
            BEFORE INSERT OR UPDATE OF issue_id, remote_market_id
            ON {CODES} FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()""")
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table, column in ((ISSUES, "redemption_code"), (CODES, "code")):
        duplicate = connection.execute(
            sa.text(f"""SELECT 1 FROM {table}
            WHERE {column} IS NOT NULL GROUP BY {column} HAVING COUNT(*) > 1 LIMIT 1""")
        ).first()
        if duplicate:
            raise RuntimeError(
                "Cross-market code values exist; keep this schema and use a forward fix."
            )
    if connection.dialect.name == "postgresql":
        op.execute(sa.text(f"DROP TRIGGER {TRIGGER} ON {CODES}"))
        op.execute(sa.text(f"DROP FUNCTION {FUNCTION}()"))
    with op.batch_alter_table(CODES) as batch:
        batch.drop_constraint(MARKET_FK, type_="foreignkey")
        batch.drop_constraint("ck_erp_compat_code_market_nonnegative", type_="check")
        batch.drop_constraint(CODE_UNIQUE, type_="unique")
        batch.create_unique_constraint(OLD_CODE_UNIQUE, ["code"])
        batch.drop_column("remote_market_id")
    with op.batch_alter_table(ISSUES) as batch:
        batch.drop_constraint(ISSUE_UNIQUE, type_="unique")
        batch.drop_constraint(PARENT_UNIQUE, type_="unique")
        batch.create_unique_constraint(OLD_ISSUE_UNIQUE, ["redemption_code"])

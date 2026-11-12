"""Durable recovery generations with shared identity and inventory guards."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_0057"
down_revision = "20261111_0056"
branch_labels = None
depends_on = None

RECOVERIES = "erp_compat_redemption_recoveries"
HISTORY = "erp_compat_redemption_historical_codes"
ISSUES = "erp_compat_redemption_code_issues"

RECOVERY_GUARD = """
CREATE OR REPLACE FUNCTION erp_compat_guard_redemption_reuse() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE owner_row erp_compat_redemption_code_issues%ROWTYPE;
            BEGIN
                IF NEW.reused_from_issue_id IS NOT NULL THEN
                    SELECT * INTO owner_row FROM erp_compat_redemption_code_issues
                        WHERE id = NEW.reused_from_issue_id FOR UPDATE;
                    IF NOT FOUND OR owner_row.reused_from_issue_id IS NOT NULL
                        OR owner_row.remote_configuration_id IS NULL
                        OR owner_row.remote_configuration_id IN ('-1', '0') THEN
                        RAISE EXCEPTION 'Reuse requires a canonical valid configuration';
                    END IF;
                    IF EXISTS (SELECT 1 FROM erp_compat_redemption_issue_codes
                        WHERE issue_id = NEW.id) THEN
                        RAISE EXCEPTION 'A linked issue cannot own code inventory';
                    END IF;
                END IF;
                IF TG_OP = 'UPDATE' AND (
                    NEW.reused_from_issue_id IS DISTINCT FROM OLD.reused_from_issue_id
                    OR NEW.remote_configuration_id IS DISTINCT FROM OLD.remote_configuration_id
                    OR NEW.remote_market_id IS DISTINCT FROM OLD.remote_market_id)
                    AND EXISTS (SELECT 1 FROM erp_compat_redemption_code_issues
                        WHERE reused_from_issue_id = NEW.id) THEN
                    IF NEW.reused_from_issue_id IS DISTINCT FROM OLD.reused_from_issue_id
                        OR NEW.remote_market_id IS DISTINCT FROM OLD.remote_market_id
                        OR NEW.active_recovery_id IS NULL
                        OR current_setting('erp.redemption_recovery', true)
                            IS DISTINCT FROM NEW.active_recovery_id::text
                        OR NOT EXISTS (
                            SELECT 1 FROM erp_compat_redemption_recoveries r
                            WHERE r.id = NEW.active_recovery_id AND r.owner_issue_id = OLD.id
                              AND r.remote_market_id = OLD.remote_market_id
                              AND r.old_configuration_id = OLD.remote_configuration_id
                              AND r.new_configuration_id = NEW.remote_configuration_id
                              AND r.new_configuration_id ~ '^[1-9][0-9]*$' AND r.status = 'APPLYING'
                        ) THEN
                        RAISE EXCEPTION 'A referenced configuration identity cannot be changed';
                    END IF;
                END IF;
                IF NEW.active_recovery_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM erp_compat_redemption_recoveries r
                    WHERE r.id = NEW.active_recovery_id AND r.owner_issue_id = NEW.id
                      AND r.remote_market_id = NEW.remote_market_id) THEN
                    RAISE EXCEPTION 'Recovery must belong to this canonical owner and market';
                END IF;
                IF NEW.current_recovery_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM erp_compat_redemption_recoveries r
                    WHERE r.id = NEW.current_recovery_id AND r.owner_issue_id = NEW.id
                      AND r.remote_market_id = NEW.remote_market_id
                      AND r.new_configuration_id = NEW.remote_configuration_id
                      AND r.status IN ('APPLYING','COMPLETED')) THEN
                    RAISE EXCEPTION 'Current generation must match this canonical configuration';
                END IF;
                RETURN NEW;
            END; $$
"""
INVENTORY_GUARD = """
CREATE OR REPLACE FUNCTION erp_compat_guard_generation_inventory() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE owner_id bigint;
BEGIN
    IF TG_TABLE_NAME = 'erp_compat_redemption_historical_codes' THEN owner_id := NEW.owner_issue_id;
        IF NOT EXISTS (SELECT 1 FROM erp_compat_redemption_recoveries r
            WHERE r.id = NEW.recovery_id AND r.owner_issue_id = owner_id
              AND r.remote_market_id = NEW.remote_market_id) THEN
            RAISE EXCEPTION 'Historical inventory must match its recovery owner';
        END IF;
    ELSE owner_id := NEW.issue_id; END IF;
    PERFORM 1 FROM erp_compat_redemption_code_issues
        WHERE id = owner_id AND remote_market_id = NEW.remote_market_id
          AND reused_from_issue_id IS NULL FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Only a canonical issue can own codes'; END IF;
    -- Serialize current and historical inventory ownership per market/code.
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.remote_market_id::text || ':' || lower(NEW.code), 0));
    IF EXISTS (SELECT 1 FROM erp_compat_redemption_historical_codes h
               WHERE h.remote_market_id = NEW.remote_market_id AND lower(h.code) = lower(NEW.code)
                 AND h.owner_issue_id <> owner_id)
       OR EXISTS (SELECT 1 FROM erp_compat_redemption_issue_codes c
               WHERE c.remote_market_id = NEW.remote_market_id AND lower(c.code) = lower(NEW.code)
                 AND c.issue_id <> owner_id)
       OR EXISTS (SELECT 1 FROM erp_compat_redemption_code_issues i
               WHERE i.remote_market_id = NEW.remote_market_id
                 AND lower(i.redemption_code) = lower(NEW.code)
                 AND i.id <> owner_id) THEN
        RAISE EXCEPTION 'Code inventory belongs to another canonical owner';
    END IF;
    RETURN NEW;
END; $$
"""


JOURNAL_GUARD = """
CREATE FUNCTION erp_compat_guard_recovery_journal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.owner_issue_id <> NEW.owner_issue_id
        OR OLD.remote_market_id <> NEW.remote_market_id
        OR OLD.old_configuration_id <> NEW.old_configuration_id
        OR OLD.history_json <> NEW.history_json THEN
        RAISE EXCEPTION 'Recovery provenance is immutable';
    END IF;
    IF OLD.status IN ('CREATING','UNCONFIRMED','RECEIPT_SAVED','APPLYING','COMPLETED') THEN
        IF OLD.snapshot_json <> NEW.snapshot_json
            OR OLD.requested_issue_id <> NEW.requested_issue_id
            OR OLD.account_id <> NEW.account_id OR OLD.key_number <> NEW.key_number THEN
            RAISE EXCEPTION 'Reserved recovery parameters are immutable';
        END IF;
        IF OLD.status <> NEW.status AND NOT (
            OLD.status='CREATING' AND NEW.status IN ('UNCONFIRMED','RECEIPT_SAVED')
            OR OLD.status='UNCONFIRMED' AND NEW.status='RECEIPT_SAVED'
                AND NEW.new_configuration_id ~ '^[1-9][0-9]*$'
            OR OLD.status='RECEIPT_SAVED' AND NEW.status='APPLYING'
            OR OLD.status='APPLYING' AND NEW.status='COMPLETED') THEN
            RAISE EXCEPTION 'Recovery writes cannot be replayed';
        END IF;
    END IF;
    IF OLD.new_configuration_id IS NOT NULL AND (
        OLD.new_configuration_id IS DISTINCT FROM NEW.new_configuration_id
        OR OLD.new_group_key IS NOT NULL
            AND OLD.new_group_key IS DISTINCT FROM NEW.new_group_key) THEN
        RAISE EXCEPTION 'A valid recovery receipt is immutable';
    END IF;
    RETURN NEW;
END; $$
"""


POLICY_GUARD = """
CREATE FUNCTION erp_compat_guard_policy_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'erp_compat_redemption_code_issues' THEN
        IF NEW.policy_update_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM erp_compat_redemption_policy_updates p WHERE p.id=NEW.policy_update_id
              AND p.owner_issue_id=NEW.id AND p.remote_market_id=NEW.remote_market_id
              AND p.configuration_id=NEW.remote_configuration_id) THEN
            RAISE EXCEPTION 'Policy update must match this canonical configuration';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.owner_issue_id<>NEW.owner_issue_id OR OLD.requested_issue_id<>NEW.requested_issue_id
       OR OLD.remote_market_id<>NEW.remote_market_id OR OLD.configuration_id<>NEW.configuration_id
       OR OLD.plan_key<>NEW.plan_key OR OLD.history_json<>NEW.history_json THEN
        RAISE EXCEPTION 'Policy update provenance is immutable';
    END IF;
    IF OLD.status<>'CHECKED' AND OLD.snapshot_json<>NEW.snapshot_json THEN
        RAISE EXCEPTION 'Reserved policy snapshot is immutable';
    END IF;
    IF OLD.status<>NEW.status AND NOT (
        OLD.status='CHECKED' AND NEW.status IN ('UPDATING','UPDATED')
        OR OLD.status='UPDATING' AND NEW.status IN ('UNCONFIRMED','UPDATED')
        OR OLD.status='UNCONFIRMED' AND NEW.status='UPDATED'
        OR OLD.status='UPDATED' AND NEW.status='APPLIED') THEN
        RAISE EXCEPTION 'Policy mutation cannot be replayed';
    END IF;
    RETURN NEW;
END; $$
"""


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    if pg:
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
    op.create_table(
        RECOVERIES,
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("owner_issue_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_issue_id", sa.BigInteger(), nullable=False),
        sa.Column("remote_market_id", sa.BigInteger(), nullable=False),
        sa.Column("key_number", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("old_configuration_id", sa.String(255), nullable=False),
        sa.Column("new_configuration_id", sa.String(255)),
        sa.Column("new_group_key", sa.String(255)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(1000)),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("proof_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proof_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["owner_issue_id", "remote_market_id"], [ISSUES + ".id", ISSUES + ".remote_market_id"]
        ),
        sa.ForeignKeyConstraint(
            ["requested_issue_id", "remote_market_id"],
            [ISSUES + ".id", ISSUES + ".remote_market_id"],
        ),
        sa.CheckConstraint("key_number between 1 and 1000 and remote_market_id > 0"),
        sa.CheckConstraint(
            "new_configuration_id is null or new_configuration_id <> old_configuration_id"
        ),
        sa.UniqueConstraint("owner_issue_id", "old_configuration_id"),
        sa.CheckConstraint(
            "status in ('CHECK_UNAVAILABLE','PRESENT','MISSING','CREATING','UNCONFIRMED',"
            "'RECEIPT_SAVED','APPLYING','COMPLETED')"
        ),
    )
    with op.batch_alter_table(ISSUES) as batch:
        batch.add_column(sa.Column("inventory_configuration_id", sa.String(255)))
        batch.add_column(sa.Column("active_recovery_id", sa.BigInteger()))
        batch.add_column(sa.Column("current_recovery_id", sa.BigInteger()))
        batch.create_foreign_key(
            "fk_erp_issue_current_recovery", RECOVERIES, ["current_recovery_id"], ["id"]
        )
        batch.add_column(sa.Column("pending_recovery_id", sa.BigInteger()))
        batch.create_foreign_key(
            "fk_erp_issue_pending_recovery", RECOVERIES, ["pending_recovery_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_erp_issue_active_recovery", RECOVERIES, ["active_recovery_id"], ["id"]
        )
    op.create_table(
        HISTORY,
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column(
            "recovery_id", sa.BigInteger(), sa.ForeignKey(RECOVERIES + ".id"), nullable=False
        ),
        sa.Column("owner_issue_id", sa.BigInteger(), nullable=False),
        sa.Column("remote_market_id", sa.BigInteger(), nullable=False),
        sa.Column("configuration_id", sa.String(255), nullable=False),
        sa.Column("code_index", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_issue_id", "remote_market_id"], [ISSUES + ".id", ISSUES + ".remote_market_id"]
        ),
        sa.UniqueConstraint("recovery_id", "code_index"),
    )
    op.create_index("ix_redemption_historical_market_code", HISTORY, ["remote_market_id", "code"])
    op.create_table(
        "erp_compat_redemption_policy_updates",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("owner_issue_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_issue_id", sa.BigInteger(), nullable=False),
        sa.Column("remote_market_id", sa.BigInteger(), nullable=False),
        sa.Column("configuration_id", sa.String(255), nullable=False),
        sa.Column("plan_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(1000)),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("owner_issue_id", "plan_key"),
        sa.ForeignKeyConstraint(
            ["owner_issue_id", "remote_market_id"], [ISSUES + ".id", ISSUES + ".remote_market_id"]
        ),
        sa.ForeignKeyConstraint(
            ["requested_issue_id", "remote_market_id"],
            [ISSUES + ".id", ISSUES + ".remote_market_id"],
        ),
        sa.CheckConstraint("status in ('CHECKED','UPDATING','UNCONFIRMED','UPDATED','APPLIED')"),
    )
    with op.batch_alter_table(ISSUES) as batch:
        batch.add_column(sa.Column("policy_update_id", sa.BigInteger()))
        batch.create_foreign_key(
            "fk_erp_issue_policy_update",
            "erp_compat_redemption_policy_updates",
            ["policy_update_id"],
            ["id"],
        )

    if pg:
        op.execute(sa.text(RECOVERY_GUARD))
        op.execute(sa.text(INVENTORY_GUARD))
        op.execute(sa.text(JOURNAL_GUARD))
        op.execute(sa.text(POLICY_GUARD))
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_policy_update_owner BEFORE INSERT OR UPDATE ON "
                + ISSUES
                + " FOR EACH ROW EXECUTE FUNCTION erp_compat_guard_policy_update()"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_policy_update_journal BEFORE UPDATE "
                "ON erp_compat_redemption_policy_updates "
                "FOR EACH ROW EXECUTE FUNCTION erp_compat_guard_policy_update()"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_recovery_journal BEFORE UPDATE ON {RECOVERIES} "
                "FOR EACH ROW EXECUTE FUNCTION erp_compat_guard_recovery_journal()"
            )
        )
        for table in (HISTORY, "erp_compat_redemption_issue_codes"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_generation_inventory BEFORE INSERT OR UPDATE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION erp_compat_guard_generation_inventory()"
                )
            )


def downgrade():
    raise RuntimeError(
        "Recovery history must be retained. Use a forward fix; do not remove this schema."
    )

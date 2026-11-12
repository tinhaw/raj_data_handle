# ruff: noqa: E501
# Keep embedded SQL readable as executable statements.
"""Allow verified special-code generations without transferring historical ownership."""

import sqlalchemy as sa
from alembic import op

revision = "20261113_0061"
down_revision = "20261113_0060"
branch_labels = None
depends_on = None

GENERATION_GUARDS = """
CREATE OR REPLACE FUNCTION erp_compat_is_special_inventory(p_owner bigint, p_configuration text, p_code text)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT p_configuration ~ '^[1-9][0-9]*$' AND EXISTS (
        SELECT 1 FROM erp_compat_redemption_code_issues i
        JOIN erp_compat_redemption_code_batches b ON b.id=i.batch_id
        WHERE i.id=p_owner AND i.reused_from_issue_id IS NULL AND i.remote_market_id>0
          AND b.remote_key_number=1 AND i.min_deposit_amount>=0
          AND i.min_deposit_amount=trunc(i.min_deposit_amount)
          AND b.redemption_type IN ('SEVEN_DAY_DEPOSIT','PREVIOUS_DAY_DEPOSIT')
          AND lower(p_code)=lower(to_char(i.claim_date,'MMDD') ||
              CASE WHEN b.redemption_type='SEVEN_DAY_DEPOSIT' THEN 'raj7days' ELSE 'raj' END ||
              CASE WHEN b.redemption_type='PREVIOUS_DAY_DEPOSIT' AND i.min_deposit_amount=0 THEN 'free'
                   WHEN b.special_code_naming='TEN_K' AND i.min_deposit_amount=10000 THEN '10K'
                   ELSE trunc(i.min_deposit_amount)::text END)
    );
$$;

CREATE OR REPLACE FUNCTION erp_compat_check_inventory_collision(p_owner bigint, p_market bigint, p_configuration text, p_code text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE other record;
BEGIN
    IF p_code IS NULL THEN RETURN; END IF;
    -- All head, collection and history writers serialize on the same case-folded key.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_market::text || ':' || lower(p_code),0));
    FOR other IN
        SELECT i.id AS owner_id, coalesce(i.inventory_configuration_id,i.remote_configuration_id) AS configuration_id
        FROM erp_compat_redemption_code_issues i
        WHERE i.remote_market_id=p_market AND lower(i.redemption_code)=lower(p_code) AND i.id<>p_owner
        UNION
        SELECT i.id, coalesce(i.inventory_configuration_id,i.remote_configuration_id)
        FROM erp_compat_redemption_issue_codes c JOIN erp_compat_redemption_code_issues i ON i.id=c.issue_id
        WHERE c.remote_market_id=p_market AND lower(c.code)=lower(p_code) AND i.id<>p_owner
        UNION
        SELECT h.owner_issue_id,h.configuration_id FROM erp_compat_redemption_historical_codes h
        WHERE h.remote_market_id=p_market AND lower(h.code)=lower(p_code) AND h.owner_issue_id<>p_owner
    LOOP
        IF p_configuration IS NOT DISTINCT FROM other.configuration_id
           OR NOT coalesce(erp_compat_is_special_inventory(p_owner,p_configuration,p_code),false)
           OR NOT coalesce(erp_compat_is_special_inventory(other.owner_id,other.configuration_id,p_code),false)
        THEN RAISE EXCEPTION 'Code inventory conflicts with another canonical configuration'; END IF;
    END LOOP;
END; $$;

CREATE OR REPLACE FUNCTION erp_compat_guard_generation_inventory() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_id bigint; owner_row erp_compat_redemption_code_issues%ROWTYPE; configuration text;
BEGIN
    IF TG_TABLE_NAME='erp_compat_redemption_historical_codes' THEN
        owner_id := NEW.owner_issue_id; configuration := NEW.configuration_id;
        IF NOT EXISTS (SELECT 1 FROM erp_compat_redemption_recoveries r
            WHERE r.id=NEW.recovery_id AND r.owner_issue_id=owner_id
              AND r.remote_market_id=NEW.remote_market_id AND r.old_configuration_id=configuration) THEN
            RAISE EXCEPTION 'Historical inventory must match its recovery generation'; END IF;
        IF TG_OP='UPDATE' AND (NEW.owner_issue_id,NEW.configuration_id,NEW.recovery_id,NEW.code,NEW.code_index,NEW.remote_market_id)
            IS DISTINCT FROM (OLD.owner_issue_id,OLD.configuration_id,OLD.recovery_id,OLD.code,OLD.code_index,OLD.remote_market_id) THEN
            RAISE EXCEPTION 'Historical inventory is immutable'; END IF;
    ELSE
        owner_id := NEW.issue_id;
        IF TG_OP='UPDATE' AND NEW.issue_id<>OLD.issue_id THEN
            RAISE EXCEPTION 'Code inventory cannot move between owners'; END IF;
    END IF;
    SELECT * INTO owner_row FROM erp_compat_redemption_code_issues
        WHERE id=owner_id AND remote_market_id=NEW.remote_market_id AND reused_from_issue_id IS NULL FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Only a canonical issue can own codes'; END IF;
    IF TG_TABLE_NAME='erp_compat_redemption_issue_codes' THEN
        configuration := coalesce(owner_row.inventory_configuration_id,owner_row.remote_configuration_id);
        IF EXISTS (SELECT 1 FROM erp_compat_redemption_issue_codes c
            WHERE c.issue_id=owner_id AND lower(c.code)=lower(NEW.code) AND c.code_index<>NEW.code_index) THEN
            RAISE EXCEPTION 'Duplicate code within configuration'; END IF;
    END IF;
    PERFORM erp_compat_check_inventory_collision(owner_id,NEW.remote_market_id,configuration,NEW.code);
    RETURN NEW;
END; $$;

CREATE OR REPLACE FUNCTION erp_compat_guard_inventory_head() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.reused_from_issue_id IS NOT NULL AND (NEW.redemption_code IS NOT NULL OR NEW.inventory_configuration_id IS NOT NULL) THEN
        RAISE EXCEPTION 'A linked issue cannot own code inventory'; END IF;
    IF NEW.inventory_configuration_id IS NOT NULL AND NEW.inventory_configuration_id IS DISTINCT FROM NEW.remote_configuration_id
        AND NOT EXISTS (SELECT 1 FROM erp_compat_redemption_recoveries r WHERE r.owner_issue_id=NEW.id
            AND r.remote_market_id=NEW.remote_market_id AND r.old_configuration_id=NEW.inventory_configuration_id) THEN
        RAISE EXCEPTION 'Inventory must identify an owned configuration generation'; END IF;
    PERFORM erp_compat_check_inventory_collision(NEW.id,NEW.remote_market_id,
        coalesce(NEW.inventory_configuration_id,NEW.remote_configuration_id),NEW.redemption_code);
    RETURN NEW;
END; $$;
CREATE TRIGGER trg_inventory_head BEFORE INSERT OR UPDATE OF redemption_code,inventory_configuration_id,remote_configuration_id,reused_from_issue_id
    ON erp_compat_redemption_code_issues FOR EACH ROW EXECUTE FUNCTION erp_compat_guard_inventory_head();
CREATE INDEX ix_erp_inventory_code_folded ON erp_compat_redemption_issue_codes(remote_market_id,lower(code));
CREATE INDEX ix_erp_inventory_head_folded ON erp_compat_redemption_code_issues(remote_market_id,lower(redemption_code));
CREATE INDEX ix_erp_inventory_history_folded ON erp_compat_redemption_historical_codes(remote_market_id,lower(code));
"""


def upgrade() -> None:
    pg = op.get_bind().dialect.name == "postgresql"
    if pg:
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
    with op.batch_alter_table("erp_compat_redemption_code_issues") as batch:
        batch.drop_constraint("uq_erp_compat_issue_market_code", type_="unique")
        batch.create_unique_constraint(
            "uq_erp_compat_issue_generation_code",
            ["remote_market_id", "inventory_configuration_id", "redemption_code"],
        )
    with op.batch_alter_table("erp_compat_redemption_issue_codes") as batch:
        batch.drop_constraint("uq_erp_compat_issue_codes_market_code", type_="unique")
        batch.create_unique_constraint("uq_erp_compat_issue_codes_owner_code", ["issue_id", "code"])
    if pg:
        op.execute(sa.text(GENERATION_GUARDS))


def downgrade() -> None:
    raise RuntimeError(
        "Configuration generation inventory must be retained; use a compatible forward fix"
    )

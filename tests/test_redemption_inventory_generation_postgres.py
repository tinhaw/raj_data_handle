# ruff: noqa: E501
# Keep embedded SQL readable as executable statements.
"""Opt-in, disposable localhost PostgreSQL recovery constraints and real service regression.

RAJ_RECOVERY_TEST_POSTGRES_URL must name a dedicated *_test database on localhost.
Never derives a URL from production settings. Each run owns a unique schema only.
"""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def migration(name):
    path = ROOT / "database/migrations/versions" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def recovery_pg():
    value = os.environ.get("RAJ_RECOVERY_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("dedicated localhost PostgreSQL is not configured")
    url = make_url(value)
    assert url.host in {"127.0.0.1", "localhost"} and url.database.endswith("_test")
    schema = "redemption_recovery_" + uuid4().hex
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET search_path TO "{schema}"')
        # Compatibility baseline plus production migrations, including reward hold constraints.
        paths = ROOT / "apps/erp-compat/server/src/main/resources/db/migration"
        for path in sorted(paths.glob("V*.sql"), key=lambda p: int(p.name.split("__")[0][1:])):
            if int(path.name.split("__")[0][1:]) <= 30:
                connection.exec_driver_sql(path.read_text())
        # Normalize database-generated unique names in this standalone fixture only.
        for table, column, expected in (
            (
                "erp_compat_redemption_code_issues",
                "redemption_code",
                "uq_erp_compat_redemption_issue_code",
            ),
            (
                "erp_compat_redemption_issue_codes",
                "code",
                "uq_erp_compat_redemption_issue_codes_code",
            ),
        ):
            for constraint in sa.inspect(connection).get_unique_constraints(table, schema=schema):
                if constraint["column_names"] == [column]:
                    old = constraint["name"].replace('"', '""')
                    connection.exec_driver_sql(
                        f'ALTER TABLE {table} RENAME CONSTRAINT "{old}" TO "{expected}"'
                    )
        for name in (
            "20261101_0053_market_scoped_redemption_codes.py",
            "20261111_0056_redemption_configuration_reuse.py",
            "20261112_0057_redemption_configuration_recovery.py",
            "20261112_0058_redemption_creation_reward_check.py",
            "20261112_0059_redemption_remote_deletion.py",
            "20261113_0060_redemption_code_naming.py",
            "20261113_0061_redemption_inventory_generations.py",
        ):
            with Operations.context(MigrationContext.configure(connection)):
                migration(name).upgrade()
        connection.commit()
    try:
        yield engine, schema
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_shared_identity_is_only_changed_by_matching_journal_transaction(recovery_pg):
    engine, schema = recovery_pg
    with engine.connect() as c:
        c.exec_driver_sql(f'SET search_path TO "{schema}"')
        c.exec_driver_sql("""INSERT INTO erp_compat_redemption_campaigns
            (id,code,name,lookback_days,status,created_at,updated_at,row_version)
            VALUES(1,'pg-recovery','PG recovery',7,'ACTIVE',now(),now(),0)""")
        c.exec_driver_sql("""INSERT INTO erp_compat_redemption_campaign_tiers
            (id,campaign_id,display_name,min_deposit_amount,bonus_amount,bonus_max_amount,
             sort_order,created_at,updated_at,row_version)
            VALUES(1,1,'all',0,2,8,0,now(),now(),0)""")
        for issue_id in (1, 2, 3):
            c.exec_driver_sql(
                """INSERT INTO erp_compat_redemption_code_issues
                (id,campaign_id,campaign_tier_id,claim_date,deposit_window_start,deposit_window_end,
                 min_deposit_amount,bonus_amount,bonus_max_amount,remote_request_id,remote_market_id,
                 workflow_status,state,created_at,updated_at,row_version)
                VALUES(%s,1,1,%s,'2026-01-01','2026-01-01',0,2,8,%s,9,
                       'CREATED','PENDING',now(),now(),0)""",
                (issue_id, f"2026-01-0{issue_id + 1}", f"fixture-{issue_id}"),
            )
        c.exec_driver_sql(
            "UPDATE erp_compat_redemption_code_issues SET remote_configuration_id='100' WHERE id=1"
        )
        c.exec_driver_sql(
            "UPDATE erp_compat_redemption_code_issues SET reused_from_issue_id=1 WHERE id=2"
        )
        c.exec_driver_sql("""INSERT INTO erp_compat_redemption_recoveries
            (id,owner_issue_id,requested_issue_id,remote_market_id,key_number,account_id,
             old_configuration_id,new_configuration_id,status,snapshot_json,history_json,created_at,updated_at)
            VALUES(1,1,2,9,1,1,'100','200','RECEIPT_SAVED','{}','{}',now(),now())""")
        c.exec_driver_sql(
            "UPDATE erp_compat_redemption_code_issues SET active_recovery_id=1 WHERE id=1"
        )
        c.commit()
        for sql in (
            "UPDATE erp_compat_redemption_code_issues SET remote_configuration_id='200' WHERE id=1",
            "UPDATE erp_compat_redemption_code_issues SET active_recovery_id=1 WHERE id=3",
            "UPDATE erp_compat_redemption_code_issues SET current_recovery_id=1 WHERE id=1",
        ):
            with pytest.raises(sa.exc.DBAPIError):
                with c.begin_nested():
                    c.exec_driver_sql(sql)
        c.exec_driver_sql("SELECT set_config('erp.redemption_recovery','1',true)")
        # A token alone does not authorize the identity update.
        with pytest.raises(sa.exc.DBAPIError):
            with c.begin_nested():
                c.exec_driver_sql(
                    "UPDATE erp_compat_redemption_code_issues "
                    "SET remote_configuration_id='200' WHERE id=1"
                )
        c.exec_driver_sql(
            "UPDATE erp_compat_redemption_recoveries SET status='APPLYING' WHERE id=1"
        )
        c.exec_driver_sql("""UPDATE erp_compat_redemption_code_issues
            SET remote_configuration_id='200',current_recovery_id=1 WHERE id=1""")
        c.exec_driver_sql(
            "UPDATE erp_compat_redemption_recoveries SET status='COMPLETED' WHERE id=1"
        )
        c.commit()
        assert (
            c.exec_driver_sql(
                "SELECT reused_from_issue_id FROM erp_compat_redemption_code_issues WHERE id=2"
            ).scalar()
            == 1
        )
        assert (
            c.exec_driver_sql(
                "SELECT remote_configuration_id FROM erp_compat_redemption_code_issues WHERE id=1"
            ).scalar()
            == "200"
        )
        # The proof token is transaction-local and cannot authorize another identity swap.
        with pytest.raises(sa.exc.DBAPIError):
            with c.begin_nested():
                c.exec_driver_sql(
                    "UPDATE erp_compat_redemption_code_issues "
                    "SET remote_configuration_id='201' WHERE id=1"
                )
        c.exec_driver_sql("""INSERT INTO erp_compat_redemption_historical_codes
            (recovery_id,owner_issue_id,remote_market_id,configuration_id,code_index,code)
            VALUES(1,1,9,'100',0,'old-random')""")
        c.commit()
        with pytest.raises(sa.exc.DBAPIError):
            with c.begin_nested():
                c.exec_driver_sql("""INSERT INTO erp_compat_redemption_issue_codes
                    (issue_id,code_index,remote_market_id,code) VALUES(3,0,9,'OLD-RANDOM')""")
        # Same owner may reuse its own code without duplicating inventory ownership.
        c.exec_driver_sql("""INSERT INTO erp_compat_redemption_issue_codes
            (issue_id,code_index,remote_market_id,code) VALUES(1,0,9,'old-random')""")
        c.commit()


def test_http_generation_and_recovery_service_on_real_postgres(recovery_pg, tmp_path):
    import subprocess

    engine, schema = recovery_pg
    url = engine.url
    assert url.username == "postgres" and url.password is None
    with engine.begin() as c:
        c.exec_driver_sql(f'SET search_path TO "{schema}"')
        # The SQL constraint test used explicit fixture identities; advance owned sequences.
        for table in (
            "erp_compat_redemption_campaigns",
            "erp_compat_redemption_campaign_tiers",
            "erp_compat_redemption_code_issues",
            "erp_compat_redemption_recoveries",
            "erp_compat_redemption_policy_updates",
        ):
            c.exec_driver_sql(
                f"SELECT setval(pg_get_serial_sequence('{table}','id'), coalesce(max(id),1)) "
                f"FROM {table}"
            )
    log = tmp_path / "java-postgres-recovery.log"
    args = [
        "mvn",
        "-q",
        "-f",
        str(ROOT / "apps/erp-compat/server/pom.xml"),
        "-Dtest=RedemptionInventoryGenerationHttpTest,RedemptionRecoveryHttpTest,RedemptionPolicyUpdateHttpTest,RedemptionReuseHttpTest",
        "-Dspring.flyway.enabled=false",
        f"-Dspring.datasource.url=jdbc:postgresql://{url.host}:{url.port}/{url.database}?currentSchema={schema}",
        "-Dspring.datasource.username=postgres",
        "-Dspring.datasource.password=",
        "test",
    ]
    with log.open("w") as output:
        result = subprocess.run(
            args, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, timeout=180
        )
    # Includes receipt/apply transactions, shared imports, and concurrent retries.
    assert result.returncode == 0, f"PostgreSQL Java recovery regression failed; see {log}"


def test_database_guards_preserve_canonical_history_and_serialize_collisions(recovery_pg):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    engine, schema = recovery_pg
    with engine.begin() as c:
        c.exec_driver_sql(f'SET search_path TO "{schema}"')
        c.exec_driver_sql("""INSERT INTO erp_compat_redemption_code_issues
            (id,campaign_id,campaign_tier_id,claim_date,deposit_window_start,deposit_window_end,
             min_deposit_amount,bonus_amount,bonus_max_amount,remote_request_id,remote_market_id,
             workflow_status,state,created_at,updated_at,row_version)
            VALUES(900001,1,1,'2039-02-02','2039-02-01','2039-02-01',0,2,8,'concurrent-fixture',9,
                   'CREATED','PENDING',now(),now(),0)""")
        for sql in (
            "UPDATE erp_compat_redemption_code_issues SET remote_configuration_id='200' WHERE id=3",
            "UPDATE erp_compat_redemption_code_issues SET inventory_configuration_id='888' WHERE id=3",
            "INSERT INTO erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) VALUES(2,0,9,'ALIAS')",
            "UPDATE erp_compat_redemption_historical_codes SET code='REWRITTEN' WHERE owner_issue_id=1",
            "INSERT INTO erp_compat_redemption_historical_codes(recovery_id,owner_issue_id,remote_market_id,configuration_id,code_index,code) VALUES(1,1,9,'999',1,'FORGED')",
        ):
            with pytest.raises(sa.exc.DBAPIError):
                with c.begin_nested():
                    c.exec_driver_sql(sql)
    barrier = Barrier(2)

    def write(issue_id):
        with engine.connect() as c:
            c.exec_driver_sql(f'SET search_path TO "{schema}"')
            c.exec_driver_sql("SET lock_timeout='5s'")
            barrier.wait(timeout=5)
            try:
                c.exec_driver_sql(
                    "UPDATE erp_compat_redemption_code_issues SET redemption_code=%s WHERE id=%s",
                    ("CONCURRENT-RANDOM" if issue_id == 3 else "concurrent-random", issue_id),
                )
                c.commit()
                return "stored"
            except sa.exc.DBAPIError:
                c.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, key) for key in (3, 900001)]
        assert sorted(f.result(timeout=10) for f in futures) == ["conflict", "stored"]
    with engine.connect() as c:
        c.exec_driver_sql(f'SET search_path TO "{schema}"')
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM erp_compat_redemption_code_issues WHERE remote_market_id=9 AND lower(redemption_code)='concurrent-random'"
            ).scalar()
            == 1
        )

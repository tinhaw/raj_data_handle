"""Regression: independent markets can reuse numeric configuration IDs.

Optionally run against a fresh, disposable loopback PostgreSQL database using
RAJ_TEST_SCOPE_DATABASE_URL. Never point this fixture at application data.
"""

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from packages.common.settings import get_settings

TABLE = "erp_compat_redemption_code_issues"


def test_market_identity_migration_preserves_data_and_refuses_unsafe_rollback(
    tmp_path, monkeypatch
):
    url = os.getenv("RAJ_TEST_SCOPE_DATABASE_URL")
    if url:
        parsed = sa.engine.make_url(url)
        assert parsed.host in {"127.0.0.1", "localhost"}
        assert parsed.database == "raj_scope_migration_test"
    else:
        url = f"sqlite:///{tmp_path / 'scope.db'}"
    async_url = url.replace("sqlite:", "sqlite+aiosqlite:").replace(
        "postgresql+psycopg:", "postgresql+asyncpg:"
    )
    monkeypatch.setenv("RAJ_DATABASE_URL", async_url)
    get_settings.cache_clear()
    engine = sa.create_engine(url)
    config = Config("alembic.ini")
    try:
        assert not sa.inspect(engine).has_table("alembic_version"), (
            "Use a fresh disposable database"
        )
        command.upgrade(config, "20260905_0042")
        with engine.begin() as conn:
            accounts = conn.execute(
                sa.text("""
                SELECT am.legacy_id, sm.legacy_id FROM remote_accounts account
                JOIN erp_compatibility_id_maps am
                  ON am.entity_type='remote_account' AND am.canonical_id=account.id
                JOIN erp_compatibility_id_maps sm
                  ON sm.entity_type='source' AND sm.canonical_id=account.source_id
                ORDER BY account.source_id
            """)
            ).fetchall()
            account_a, market_a = accounts[0]
            account_b, market_b = next(row for row in accounts if row[1] != market_a)
            conn.execute(
                sa.text("""
                INSERT INTO erp_compat_redemption_campaigns
                (id,code,name,status,lookback_days,created_at,updated_at,row_version)
                VALUES (100,'SCOPE-MIGRATION','scope','ACTIVE',7,
                        CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,0)
            """)
            )
            conn.execute(
                sa.text("""
                INSERT INTO erp_compat_redemption_campaign_tiers
                (id,campaign_id,display_name,min_deposit_amount,bonus_amount,bonus_max_amount,sort_order,created_at,updated_at)
                VALUES (100,100,'scope',0,1,3,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            """)
            )
            conn.execute(
                sa.text("""
                INSERT INTO erp_compat_redemption_code_tasks (id,grouping_key,created_at)
                VALUES (100,'scope',CURRENT_TIMESTAMP)
            """)
            )
            for index, account in enumerate([account_a, account_b, account_a]):
                conn.execute(
                    sa.text("""
                    INSERT INTO erp_compat_redemption_code_batches
                    (id,campaign_id,task_id,remote_connection_id,claim_date_from,claim_date_to,
                    lookback_days,expected_code_count,status,created_at,updated_at,row_version)
                    VALUES (:id,100,100,:account,'2026-09-05','2026-09-07',7,1,'CREATING',
                            CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,0)
                """),
                    {"id": 100 + index, "account": account},
                )
                conn.execute(
                    sa.text(f"""
                    INSERT INTO {TABLE}
                    (id,campaign_id,campaign_tier_id,batch_id,claim_date,deposit_window_start,deposit_window_end,
                    min_deposit_amount,bonus_amount,bonus_max_amount,remote_request_id,remote_configuration_id,
                    created_at,updated_at,row_version)
                    VALUES (:id,100,100,:id,:day,'2026-09-01','2026-09-04',0,1,3,:request,:config,
                    CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,7)
                """),
                    {
                        "id": 100 + index,
                        "day": f"2026-09-{5 + index:02}",
                        "request": f"scope-{index}",
                        "config": "1632" if index == 0 else None,
                    },
                )
            conn.execute(
                sa.text(
                    "INSERT INTO erp_compat_redemption_issue_codes VALUES (100,0,'PRESERVE-CODE')"
                )
            )
            conn.execute(
                sa.text(
                    "UPDATE erp_compat_redemption_code_batches "
                    "SET remote_connection_id=999 WHERE id=101"
                )
            )
            conn.execute(
                sa.text(f"UPDATE {TABLE} SET remote_configuration_id='unresolved' WHERE id=101")
            )

        # Unknown provenance must fail before even adding the new column.
        with pytest.raises(RuntimeError, match="Remote market cannot be resolved"):
            command.upgrade(config, "20260905_0043")
        assert "remote_market_id" not in {c["name"] for c in sa.inspect(engine).get_columns(TABLE)}
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE erp_compat_redemption_code_batches "
                    "SET remote_connection_id=:account WHERE id=101"
                ),
                {"account": account_b},
            )
            conn.execute(sa.text(f"UPDATE {TABLE} SET remote_configuration_id=NULL WHERE id=101"))

        command.upgrade(config, "20260905_0043")
        with engine.begin() as conn:
            assert conn.execute(
                sa.text(f"SELECT id,remote_market_id,row_version FROM {TABLE} ORDER BY id")
            ).fetchall() == [
                (100, market_a, 7),
                (101, market_b, 7),
                (102, market_a, 7),
            ]
            assert (
                conn.execute(
                    sa.text("SELECT code FROM erp_compat_redemption_issue_codes")
                ).scalar_one()
                == "PRESERVE-CODE"
            )
            conn.execute(sa.text(f"UPDATE {TABLE} SET remote_configuration_id='1632' WHERE id=101"))
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(sa.text(f"UPDATE {TABLE} SET remote_configuration_id='1632' WHERE id=102"))
        with pytest.raises(RuntimeError, match="Cross-market configuration IDs exist"):
            command.downgrade(config, "20260905_0042")
        with engine.begin() as conn:
            assert conn.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() == 3
            conn.execute(sa.text(f"UPDATE {TABLE} SET remote_configuration_id=NULL WHERE id=101"))
            conn.execute(
                sa.text(f"UPDATE {TABLE} SET remote_create_receipt_id='receipt' WHERE id=102")
            )
        with pytest.raises(RuntimeError, match="Unregistered remote receipts exist"):
            command.downgrade(config, "20260905_0042")
        with engine.begin() as conn:
            conn.execute(sa.text(f"UPDATE {TABLE} SET remote_create_receipt_id=NULL WHERE id=102"))
        command.downgrade(config, "20260905_0042")
        command.upgrade(config, "20260905_0043")
        with engine.begin() as conn:
            assert (
                conn.execute(
                    sa.text("SELECT code FROM erp_compat_redemption_issue_codes")
                ).scalar_one()
                == "PRESERVE-CODE"
            )
            # A task's recorded market is not an account-dependent computed key.
            conn.execute(
                sa.text(
                    "UPDATE erp_compat_redemption_code_batches "
                    "SET remote_connection_id=999 WHERE id=100"
                )
            )
            assert (
                conn.execute(
                    sa.text(f"SELECT remote_market_id FROM {TABLE} WHERE id=100")
                ).scalar_one()
                == market_a
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()

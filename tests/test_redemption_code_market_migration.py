from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from packages.common.settings import get_settings


@pytest.fixture
def market_database(tmp_path: Path, monkeypatch):
    path = tmp_path / "market-codes.db"
    monkeypatch.setenv("RAJ_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "20261101_0052")
    with sqlite3.connect(path) as connection:
        connection.execute("""INSERT INTO erp_compat_redemption_campaigns
            (id,code,name,created_at,updated_at)
            VALUES(1,'MARKET-CODES','Market codes',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
        connection.execute("""INSERT INTO erp_compat_redemption_campaign_tiers
            (id,campaign_id,min_deposit_amount,bonus_amount,bonus_max_amount,created_at,updated_at)
            VALUES(1,1,0,5,7,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
        connection.execute("""INSERT INTO erp_compat_redemption_code_tasks
            (id,grouping_key,created_at,task_date,daily_sequence)
            VALUES(1,'market-codes',CURRENT_TIMESTAMP,'2026-11-01',1)""")
        connection.execute("""INSERT INTO erp_compat_redemption_code_batches
            (id,campaign_id,claim_date_from,claim_date_to,lookback_days,expected_code_count,task_id,
             created_at,updated_at,subtask_date,subtask_daily_sequence)
            VALUES(1,1,'2026-11-01','2026-11-03',7,3,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'2026-11-01',1)""")
        for issue_id, market, code in ((1, 11, "FIRST-A"), (2, 22, "FIRST-B"), (3, 11, None)):
            day = f"2026-11-{issue_id:02d}"
            connection.execute(
                """INSERT INTO erp_compat_redemption_code_issues
                (id,campaign_id,campaign_tier_id,batch_id,claim_date,deposit_window_start,deposit_window_end,
                 min_deposit_amount,bonus_amount,bonus_max_amount,remote_request_id,remote_market_id,
                 redemption_code,created_at,updated_at)
                VALUES(?,1,1,1,?,?,?,0,5,7,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                (issue_id, day, day, day, f"market-code-{issue_id}", market, code),
            )
        connection.executemany(
            "INSERT INTO erp_compat_redemption_issue_codes(issue_id,code_index,code) VALUES(?,?,?)",
            [(1, 0, "FIRST-A"), (1, 1, "SHARED"), (2, 0, "FIRST-B")],
        )
    try:
        yield config, path
    finally:
        get_settings.cache_clear()


def test_code_market_upgrade_preserves_rows_and_round_trips(market_database):
    config, path = market_database
    command.upgrade(config, "20261101_0053")
    expected = [(1, 0, "FIRST-A", 11), (1, 1, "SHARED", 11), (2, 0, "FIRST-B", 22)]
    with sqlite3.connect(path) as c:
        assert (
            c.execute(
                "SELECT issue_id,code_index,code,remote_market_id "
                "FROM erp_compat_redemption_issue_codes ORDER BY issue_id,code_index"
            ).fetchall()
            == expected
        )
    command.downgrade(config, "20261101_0052")
    with sqlite3.connect(path) as c:
        assert c.execute(
            "SELECT issue_id,code_index,code FROM erp_compat_redemption_issue_codes "
            "ORDER BY issue_id,code_index"
        ).fetchall() == [row[:3] for row in expected]
    command.upgrade(config, "20261101_0053")
    with sqlite3.connect(path) as c:
        assert (
            c.execute(
                "SELECT issue_id,code_index,code,remote_market_id "
                "FROM erp_compat_redemption_issue_codes ORDER BY issue_id,code_index"
            ).fetchall()
            == expected
        )


def test_market_identity_is_enforced_and_unsafe_downgrade_refused(market_database):
    config, path = market_database
    command.upgrade(config, "20261101_0053")
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("INSERT INTO erp_compat_redemption_issue_codes VALUES(2,1,'SHARED',22)")
        c.execute(
            "UPDATE erp_compat_redemption_code_issues SET redemption_code='FIRST-A' WHERE id=2"
        )
        c.execute(
            "UPDATE erp_compat_redemption_issue_codes SET code='FIRST-A' "
            "WHERE issue_id=2 AND code_index=0"
        )
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO erp_compat_redemption_issue_codes VALUES(3,0,'SHARED',11)")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO erp_compat_redemption_issue_codes VALUES(3,0,'WRONG-MARKET',22)")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(
                "UPDATE erp_compat_redemption_code_issues SET redemption_code='FIRST-A' WHERE id=3"
            )
    with pytest.raises(RuntimeError, match="Cross-market code values exist"):
        command.downgrade(config, "20261101_0052")
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("20261101_0053",)
        assert c.execute("SELECT count(*) FROM erp_compat_redemption_issue_codes").fetchone() == (
            4,
        )

import sqlite3

import pytest
from alembic import command
from test_redemption_code_market_migration import market_database as _market_database


@pytest.fixture
def recovery_database(tmp_path, monkeypatch):
    yield from _market_database.__wrapped__(tmp_path, monkeypatch)


def test_recovery_migration_is_additive_and_generation_journal_has_unique_owner_identity(
    recovery_database,
):
    config, path = recovery_database
    command.upgrade(config, "20261111_0056")
    with sqlite3.connect(path) as c:
        before = c.execute(
            "SELECT * FROM erp_compat_redemption_issue_codes ORDER BY issue_id,code_index"
        ).fetchall()
    command.upgrade(config, "20261112_0057")
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA foreign_keys=ON")
        assert (
            c.execute(
                "SELECT * FROM erp_compat_redemption_issue_codes ORDER BY issue_id,code_index"
            ).fetchall()
            == before
        )
        statement = """INSERT INTO erp_compat_redemption_recoveries
            (owner_issue_id,requested_issue_id,remote_market_id,key_number,account_id,
             old_configuration_id,status,snapshot_json,history_json,created_at,updated_at)
            VALUES(1,3,?,1,1,'123','MISSING','{}','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(statement, (22,))
        c.execute(statement, (11,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(statement, (11,))
        assert c.execute("SELECT count(*) FROM erp_compat_redemption_recoveries").fetchone() == (1,)
    with pytest.raises(RuntimeError, match="Recovery history must be retained"):
        command.downgrade(config, "20261111_0056")

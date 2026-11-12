import sqlite3

import pytest
from alembic import command
from test_redemption_code_market_migration import market_database as _market_database


@pytest.fixture
def deletion_database(tmp_path, monkeypatch):
    yield from _market_database.__wrapped__(tmp_path, monkeypatch)


def test_deletion_migration_preserves_stock_and_execution_can_only_be_claimed_once(
    deletion_database,
):
    config, path = deletion_database
    command.upgrade(config, "20261112_0058")
    with sqlite3.connect(path) as c:
        before = c.execute("SELECT * FROM erp_compat_redemption_issue_codes").fetchall()
    command.upgrade(config, "20261112_0059")
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT * FROM erp_compat_redemption_issue_codes").fetchall() == before
        c.execute("""INSERT INTO erp_compat_redemption_deletions
          (owner_issue_id,requested_issue_id,configuration_id,status,snapshot_json,remote_json,
           created_at,updated_at)
           VALUES(1,1,'3403','DELETING','{}','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
        claim = """UPDATE erp_compat_redemption_deletions SET remote_attempted=true
                   WHERE id=1 AND status='DELETING' AND remote_attempted=false RETURNING id"""
        assert c.execute(claim).fetchone() == (1,)
        assert c.execute(claim).fetchone() is None
        c.execute("""INSERT INTO erp_compat_redemption_task_deletions
          (task_id,status,scope_json,items_json,created_at,updated_at)
          VALUES((SELECT task_id FROM erp_compat_redemption_code_batches LIMIT 1),
          'RUNNING','[]','[]',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
        assert c.execute("SELECT busy FROM erp_compat_redemption_task_deletions").fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM erp_compat_redemption_deletions").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE erp_compat_redemption_deletions SET status='RETRY_DELETE'")
    with pytest.raises(RuntimeError, match="deletion records"):
        command.downgrade(config, "20261112_0058")

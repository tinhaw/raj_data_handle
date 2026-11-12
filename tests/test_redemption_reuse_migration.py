import sqlite3

import pytest
from alembic import command
from test_redemption_code_market_migration import market_database as _market_database


@pytest.fixture
def reuse_database(tmp_path, monkeypatch):
    yield from _market_database.__wrapped__(tmp_path, monkeypatch)


def test_additive_migration_keeps_inventory_and_rejects_cross_market_and_self_links(reuse_database):
    config, path = reuse_database
    command.upgrade(config, "20261106_0055")
    with sqlite3.connect(path) as connection:
        before = connection.execute(
            "SELECT * FROM erp_compat_redemption_issue_codes ORDER BY issue_id,code_index"
        ).fetchall()
    command.upgrade(config, "20261111_0056")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert (
            connection.execute(
                "SELECT * FROM erp_compat_redemption_issue_codes ORDER BY issue_id,code_index"
            ).fetchall()
            == before
        )
        connection.execute(
            "UPDATE erp_compat_redemption_code_issues "
            "SET remote_configuration_id='123',workflow_status='CODE_IMPORTED',"
            "state='GENERATED' WHERE id=1"
        )
        for owner in (2, 3):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE erp_compat_redemption_code_issues "
                    "SET reused_from_issue_id=?,workflow_status='CREATED' WHERE id=3",
                    (owner,),
                )
        connection.execute(
            "UPDATE erp_compat_redemption_code_issues "
            "SET reused_from_issue_id=1,workflow_status='CREATED' WHERE id=3"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE erp_compat_redemption_code_issues "
                "SET remote_configuration_id='456' WHERE id=3"
            )
        assert connection.execute(
            "SELECT count(*) FROM erp_compat_redemption_issue_codes"
        ).fetchone() == (3,)
    with pytest.raises(RuntimeError, match="Reuse links exist"):
        command.downgrade(config, "20261106_0055")
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT reused_from_issue_id FROM erp_compat_redemption_code_issues WHERE id=3"
        ).fetchone() == (1,)


def test_unused_reuse_schema_can_be_rolled_back_without_data_loss(reuse_database):
    config, path = reuse_database
    command.upgrade(config, "20261111_0056")
    command.downgrade(config, "20261106_0055")
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM erp_compat_redemption_issue_codes"
        ).fetchone() == (3,)

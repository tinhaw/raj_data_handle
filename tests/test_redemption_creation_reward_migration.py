import sqlite3

import pytest
from alembic import command
from test_redemption_code_market_migration import market_database as _market_database


@pytest.fixture
def reward_database(tmp_path, monkeypatch):
    yield from _market_database.__wrapped__(tmp_path, monkeypatch)


def test_reward_holds_preserve_data_and_keep_shared_identity_and_inventory_guards(reward_database):
    config, path = reward_database
    command.upgrade(config, "20261112_0057")
    with sqlite3.connect(path) as connection:
        before = connection.execute(
            "SELECT * FROM erp_compat_redemption_code_issues ORDER BY id"
        ).fetchall()
        stock = connection.execute(
            "SELECT * FROM erp_compat_redemption_issue_codes ORDER BY issue_id,code_index"
        ).fetchall()
    command.upgrade(config, "20261112_0058")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert (
            connection.execute(
                "SELECT * FROM erp_compat_redemption_code_issues ORDER BY id"
            ).fetchall()
            == before
        )
        assert (
            connection.execute(
                "SELECT * FROM erp_compat_redemption_issue_codes ORDER BY issue_id,code_index"
            ).fetchall()
            == stock
        )
        connection.execute(
            "UPDATE erp_compat_redemption_code_issues SET remote_configuration_id='123',"
            "workflow_status='CODE_IMPORTED' WHERE id=1"
        )
        for state in ("REWARD_CHECK_REQUIRED", "REWARD_CONFIRM_REQUIRED", "CREATED"):
            connection.execute(
                "UPDATE erp_compat_redemption_code_issues SET reused_from_issue_id=1,"
                "workflow_status=? WHERE id=3",
                (state,),
            )
        for change in (
            "workflow_status='CODE_IMPORTED'",
            "state='GENERATED'",
            "redemption_code='COPY'",
            "remote_configuration_id='123'",
            "reused_from_issue_id=3",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"UPDATE erp_compat_redemption_code_issues SET {change} WHERE id=3"
                )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE erp_compat_redemption_code_issues SET workflow_status='UNKNOWN' WHERE id=1"
            )
    with pytest.raises(RuntimeError, match="Reward verification states must be retained"):
        command.downgrade(config, "20261112_0057")

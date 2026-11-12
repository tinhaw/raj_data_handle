import sqlite3

import pytest
from alembic import command
from test_redemption_code_market_migration import market_database as _market_database


@pytest.fixture
def naming_database(tmp_path, monkeypatch):
    yield from _market_database.__wrapped__(tmp_path, monkeypatch)


def test_naming_upgrade_preserves_old_batches_codes_and_shared_guards(naming_database):
    config, path = naming_database
    command.upgrade(config, "20261112_0059")
    tables = (
        "erp_compat_redemption_code_batches",
        "erp_compat_redemption_code_issues",
        "erp_compat_redemption_issue_codes",
    )
    with sqlite3.connect(path) as conn:
        before = {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables
        }
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({tables[0]})")]
        triggers = conn.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        ).fetchall()
    command.upgrade(config, "20261113_0060")
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert (
            conn.execute(f"SELECT {','.join(columns)} FROM {tables[0]} ORDER BY 1").fetchall()
            == before[tables[0]]
        )
        for table in tables[1:]:
            assert conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() == before[table]
        assert conn.execute(f"SELECT special_code_naming FROM {tables[0]}").fetchall() == [
            ("ORIGINAL",)
        ]
        assert (
            conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
            ).fetchall()
            == triggers
        )
        for invalid in ("UNKNOWN", "10k", None):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f"UPDATE {tables[0]} SET special_code_naming=? WHERE id=1", (invalid,))
        conn.execute(f"UPDATE {tables[0]} SET special_code_naming='TEN_K' WHERE id=1")
        assert conn.execute(
            f"SELECT special_code_naming FROM {tables[0]} WHERE id=1"
        ).fetchone() == ("TEN_K",)
    with pytest.raises(RuntimeError, match="Code naming snapshots must be retained"):
        command.downgrade(config, "20261112_0059")

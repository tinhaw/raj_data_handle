import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from packages.common.settings import get_settings


def test_0042_preserves_old_presets_and_isolates_daily(tmp_path, monkeypatch):
    database = tmp_path / "presets.db"
    monkeypatch.setenv("RAJ_DATABASE_URL", f"sqlite+aiosqlite:///{database}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "20260905_0041")
        with sqlite3.connect(database) as conn:
            account = conn.execute("SELECT id FROM remote_accounts LIMIT 1").fetchone()[0]
            conn.execute(
                "INSERT INTO remote_account_reward_tier_presets "
                "(account_id, tiers_json, tag_snapshot_json, saved_at, updated_at, row_version) "
                "VALUES (?, '[]', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 7)",
                (account,),
            )
        command.upgrade(config, "20260905_0042")
        with sqlite3.connect(database) as conn:
            assert conn.execute(
                "SELECT redemption_type,row_version FROM remote_account_reward_tier_presets"
            ).fetchall() == [("SEVEN_DAY_DEPOSIT", 7)]
            conn.execute(
                "INSERT INTO remote_account_reward_tier_presets "
                "(account_id, redemption_type, tiers_json, tag_snapshot_json, "
                "saved_at, updated_at, row_version) "
                "VALUES (?, 'PREVIOUS_DAY_DEPOSIT', '[]', '[]', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)",
                (account,),
            )
            assert (
                conn.execute("SELECT count(*) FROM remote_account_reward_tier_presets").fetchone()[
                    0
                ]
                == 2
            )
        with pytest.raises(RuntimeError, match="Daily presets exist"):
            command.downgrade(config, "20260905_0041")
    finally:
        get_settings.cache_clear()

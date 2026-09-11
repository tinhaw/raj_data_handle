import sqlite3

from alembic import command
from alembic.config import Config

from packages.common.settings import get_settings


def test_0044_preserves_accounts_and_defaults_periodic_login_off(tmp_path, monkeypatch):
    database = tmp_path / "sessions-migration.db"
    monkeypatch.setenv("RAJ_DATABASE_URL", f"sqlite+aiosqlite:///{database}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "20260905_0043")
        with sqlite3.connect(database) as connection:
            original = connection.execute(
                "SELECT id,source_id,credential_version FROM remote_accounts ORDER BY id"
            ).fetchall()
            original_tasks = connection.execute(
                "SELECT count(*) FROM erp_compat_redemption_code_issues"
            ).fetchone()
        command.upgrade(config, "20260905_0044")
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT id,source_id,credential_version FROM remote_accounts ORDER BY id"
            ).fetchall() == original
            assert connection.execute(
                "SELECT count(*) FROM erp_compat_redemption_code_issues"
            ).fetchone() == original_tasks
            assert connection.execute(
                "SELECT count(*) FROM remote_accounts WHERE auto_relogin <> 1 "
                "OR relogin_interval_minutes IS NOT NULL OR next_relogin_at IS NOT NULL "
                "OR session_ciphertext IS NOT NULL"
            ).fetchone() == (0,)
        command.downgrade(config, "20260905_0043")
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT id,source_id,credential_version FROM remote_accounts ORDER BY id"
            ).fetchall() == original
    finally:
        get_settings.cache_clear()

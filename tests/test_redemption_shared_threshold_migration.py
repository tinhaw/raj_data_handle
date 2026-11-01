import sqlite3

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from packages.common.settings import get_settings

PREVIOUS = "20260911_0051"
TARGET = "20261101_0052"
TABLES = ("erp_redemption_campaign_tiers", "erp_compat_redemption_campaign_tiers")


@pytest.fixture
def threshold_database(tmp_path, monkeypatch):
    path = tmp_path / "shared-thresholds.db"
    monkeypatch.setenv("RAJ_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, PREVIOUS)
        with sqlite3.connect(path) as connection:
            for table, campaign_id in zip(TABLES, ("local-campaign", 1), strict=True):
                campaigns = table.removesuffix("_tiers") + "s"
                connection.execute(
                    f"INSERT INTO {campaigns} "
                    "(id, code, name, status, lookback_days, row_version, created_at, updated_at) "
                    "VALUES (?, 'SHARED', 'Shared thresholds', 'ACTIVE', 7, 1, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (campaign_id,),
                )
                _insert_tier(connection, table, 1)
        yield path, config
    finally:
        get_settings.cache_clear()


def _insert_tier(connection, table, number):
    legacy = table == TABLES[0]
    connection.execute(
        f"INSERT INTO {table} "
        "(id, campaign_id, display_name, min_deposit_amount, bonus_amount, "
        "bonus_max_amount, sort_order, row_version"
        + ("" if legacy else ", created_at, updated_at")
        + ") VALUES (?, ?, ?, 0, 5, ?, ?, 1"
        + ("" if legacy else ", CURRENT_TIMESTAMP, CURRENT_TIMESTAMP")
        + ")",
        (
            str(number) if legacy else number,
            "local-campaign" if legacy else 1,
            "All users" if number == 1 else "Game count zero",
            7 if number == 1 else 17,
            number,
        ),
    )


def _has_threshold_unique(path, table):
    engine = create_engine(f"sqlite:///{path}")
    try:
        return any(
            set(constraint["column_names"]) == {"campaign_id", "min_deposit_amount"}
            for constraint in inspect(engine).get_unique_constraints(table)
        )
    finally:
        engine.dispose()


def test_upgrade_preserves_existing_tiers_and_allows_shared_thresholds(threshold_database):
    path, config = threshold_database
    with sqlite3.connect(path) as connection:
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in TABLES
        }
    command.upgrade(config, TARGET)
    with sqlite3.connect(path) as connection:
        for table in TABLES:
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == before[table]
            assert not _has_threshold_unique(path, table)
            _insert_tier(connection, table, 2)
            assert connection.execute(
                f"SELECT display_name, bonus_max_amount FROM {table} ORDER BY sort_order"
            ).fetchall() == [("All users", 7), ("Game count zero", 17)]


@pytest.mark.parametrize("duplicate_table", TABLES)
def test_downgrade_rejects_duplicates_before_restoring_either_constraint(
    threshold_database, duplicate_table
):
    path, config = threshold_database
    command.upgrade(config, TARGET)
    with sqlite3.connect(path) as connection:
        _insert_tier(connection, duplicate_table, 2)
    with pytest.raises(RuntimeError, match="Shared redemption thresholds exist"):
        command.downgrade(config, PREVIOUS)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (TARGET,)
        assert connection.execute(f"SELECT COUNT(*) FROM {duplicate_table}").fetchone() == (2,)
    for table in TABLES:
        assert not _has_threshold_unique(path, table)


def test_clean_downgrade_restores_uniqueness_and_can_upgrade_again(threshold_database):
    path, config = threshold_database
    command.upgrade(config, TARGET)
    command.downgrade(config, PREVIOUS)
    for table in TABLES:
        assert _has_threshold_unique(path, table)
        with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
            _insert_tier(connection, table, 2)
    command.upgrade(config, TARGET)
    for table in TABLES:
        assert not _has_threshold_unique(path, table)

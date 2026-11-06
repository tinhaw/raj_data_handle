import importlib

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations

from packages.domain.models import Base


def test_claim_migration_matches_models_and_blocks_destructive_downgrade(monkeypatch):
    migration = importlib.import_module(
        "database.migrations.versions.20261105_0054_redemption_claim_statistics"
    )
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    for name, table in Base.metadata.tables.items():
        if name.startswith("erp_redemption_claim_"):
            table.to_metadata(metadata)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        monkeypatch.setattr(migration, "op", Operations(context))
        migration.upgrade()
        assert compare_metadata(context, metadata) == []
        connection.execute(
            sa.text(
                "INSERT INTO erp_redemption_claim_schedules "
                "(task_id,enabled,interval_minutes,row_version,actor_user_id) "
                "VALUES (1,0,30,0,1)"
            )
        )
        with pytest.raises(RuntimeError, match="retain schema"):
            migration.downgrade()
        assert "erp_redemption_claim_schedules" in sa.inspect(connection).get_table_names()
        connection.execute(sa.text("DELETE FROM erp_redemption_claim_schedules"))
        migration.downgrade()
        assert not sa.inspect(connection).get_table_names()
    engine.dispose()

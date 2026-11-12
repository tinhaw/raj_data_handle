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
    identity = importlib.import_module(
        "database.migrations.versions.20261106_0055_redemption_claim_user_identity"
    )
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    for name, table in Base.metadata.tables.items():
        if name.startswith("erp_redemption_claim_"):
            table.to_metadata(metadata)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        monkeypatch.setattr(migration, "op", Operations(context))
        monkeypatch.setattr(identity, "op", Operations(context))
        migration.upgrade()
        assert sa.inspect(connection).get_pk_constraint(identity.TABLE)["constrained_columns"] == [
            "group_id", "remote_id",
        ]
        identity.upgrade()
        assert compare_metadata(context, metadata) == []
        assert sa.inspect(connection).get_pk_constraint(identity.TABLE)["constrained_columns"] == [
            "group_id", "remote_id", "uid",
        ]
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
        identity.downgrade()
        migration.downgrade()
        assert not sa.inspect(connection).get_table_names()
    engine.dispose()


def test_identity_migration_preserves_old_facts_and_blocks_lossy_downgrade(monkeypatch):
    base = importlib.import_module(
        "database.migrations.versions.20261105_0054_redemption_claim_statistics"
    )
    identity = importlib.import_module(
        "database.migrations.versions.20261106_0055_redemption_claim_user_identity"
    )
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        operation = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(base, "op", operation)
        monkeypatch.setattr(identity, "op", operation)
        base.upgrade()
        connection.execute(sa.text("""
            INSERT INTO erp_redemption_claim_groups
                (id,task_id,issue_id,batch_id,source_id,group_key,column_key,snapshot,version)
            VALUES ('synthetic-group',1,1,1,'rajwin','synthetic-key','column','{}',1)
        """))
        insert = sa.text("""
            INSERT INTO erp_redemption_claim_records
                (group_id,remote_id,code,uid,receive_time,received_at,claim_date,amount,gift_type)
            VALUES ('synthetic-group','42','SYNTHETIC',:uid,'2026-11-01 00:00:00',
                    '2026-10-31 18:30:00','2026-11-01',5,0)
        """)
        connection.execute(insert, {"uid": "800001"})
        before = connection.execute(sa.text(f"SELECT * FROM {identity.TABLE}")).all()
        identity.upgrade()
        assert connection.execute(sa.text(f"SELECT * FROM {identity.TABLE}")).all() == before
        connection.execute(insert, {"uid": "800002"})
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(insert, {"uid": "800002"})
        with pytest.raises(RuntimeError, match="retain schema and facts"):
            identity.downgrade()
        assert connection.scalar(sa.text(f"SELECT COUNT(*) FROM {identity.TABLE}")) == 2
        assert sa.inspect(connection).get_pk_constraint(identity.TABLE)["constrained_columns"] == [
            "group_id", "remote_id", "uid",
        ]
        assert {index["name"] for index in sa.inspect(connection).get_indexes(identity.TABLE)} == {
            "ix_claim_record_day_code"
        }
        connection.execute(sa.text(f"DELETE FROM {identity.TABLE} WHERE uid='800002'"))
        identity.downgrade()
        assert connection.execute(sa.text(f"SELECT * FROM {identity.TABLE}")).all() == before
        assert sa.inspect(connection).get_pk_constraint(identity.TABLE)["constrained_columns"] == [
            "group_id", "remote_id",
        ]
    engine.dispose()

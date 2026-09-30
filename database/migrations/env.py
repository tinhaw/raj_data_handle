from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from database.migrations.autogenerate import include_object
from packages.common.database import configparser_safe_database_url
from packages.common.settings import get_settings
from packages.domain.models import Base

config = context.config
if config.config_file_name is not None:
    # Alembic can also run inside the API/worker process (and in-process tests).
    # Preserve loggers that the host application configured before migrations.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

database_url = get_settings().database_url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")
# Alembic stores this value through ConfigParser, where percent signs are
# interpolation markers. URL-encoded credentials can legitimately contain
# them, so escape only the ConfigParser representation.
config.set_main_option("sqlalchemy.url", configparser_safe_database_url(database_url))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

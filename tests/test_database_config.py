from alembic.config import Config

from packages.common.database import configparser_safe_database_url


def test_alembic_url_escapes_configparser_percent_without_changing_value() -> None:
    database_url = "postgresql+psycopg://user:encoded%40value@db.example/data_handle"
    config = Config()
    config.set_main_option(
        "sqlalchemy.url",
        configparser_safe_database_url(database_url),
    )
    assert config.get_main_option("sqlalchemy.url") == database_url

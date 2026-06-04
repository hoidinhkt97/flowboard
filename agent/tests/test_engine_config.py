"""The engine URL must come from config so production can point at Postgres
while tests/dev stay on SQLite."""
from flowboard.config import DATABASE_URL


def test_database_url_defaults_to_sqlite():
    assert DATABASE_URL.startswith("sqlite")


def test_engine_uses_database_url():
    from flowboard.db.session import engine
    assert engine.url.get_backend_name() == "sqlite"

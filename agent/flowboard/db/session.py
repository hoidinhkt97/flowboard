from contextlib import contextmanager

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from flowboard.config import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _connection_record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def _sqlite_targeted_migration() -> None:
    from sqlalchemy import inspect
    from flowboard.db import models  # noqa: F401

    with engine.connect() as conn:
        insp = inspect(conn)
        if insp.has_table("asset"):
            cols = {c["name"] for c in insp.get_columns("asset")}
            if "url" not in cols:
                models.Asset.__table__.drop(conn, checkfirst=True)
                conn.commit()


def init_db() -> None:
    if _is_sqlite:
        _sqlite_targeted_migration()
        from flowboard.db import models  # noqa: F401
        SQLModel.metadata.create_all(engine)
    else:
        import os
        from alembic import command
        from alembic.config import Config
        ini_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
        )
        alembic_cfg = Config(ini_path)
        command.upgrade(alembic_cfg, "head")


@contextmanager
def get_session():
    with Session(engine) as session:
        yield session

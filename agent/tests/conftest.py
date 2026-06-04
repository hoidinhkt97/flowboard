import os
import tempfile
from pathlib import Path

import pytest

# Point Flowboard at an isolated temp dir BEFORE importing the app.
_TMPDIR = tempfile.mkdtemp(prefix="flowboard-test-")
os.environ["FLOWBOARD_STORAGE"] = _TMPDIR
os.environ["FLOWBOARD_DB"] = str(Path(_TMPDIR) / "test.db")
# Force the deterministic mock planner in tests — never spawn `claude` subprocess.
# Individual tests that want to exercise the CLI path patch the module directly.
os.environ["FLOWBOARD_PLANNER_BACKEND"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from flowboard.db.session import engine  # noqa: E402
from flowboard.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """Drop + recreate all tables before each test so state is isolated."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth(client):
    client.post("/api/account/register",
                json={"email": "fixture@example.com", "password": "pw123456"})
    tok = client.post("/api/account/login",
                      json={"email": "fixture@example.com", "password": "pw123456"}
                      ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}

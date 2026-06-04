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


@pytest.fixture(autouse=True)
def _seed_default_paygate_tier():
    """Most tests exercise downstream behaviour (variant_count, ref_media_ids,
    SDK payload shape, etc.) and don't care about the upstream tier-resolution
    chain. Pre-Phase-1, the worker silently defaulted to PAYGATE_TIER_ONE when
    no signal was present, so tests didn't have to think about tier at all.
    Phase 1 made that fail loud — every gen now requires a tier signal — so
    we keep the test-time ergonomics by simulating the "extension already
    sniffed Pro" state by default. Tests that specifically want to exercise
    the no-tier path (e.g. test_processor_tier_fallback.py) reset the cache
    in their own module-local autouse fixture, which runs after this one and
    wins.

    Phase 2 (registry dispatch): the worker now resolves FlowClient from
    the ConnectionRegistry instead of the global singleton. Seed a
    FlowClient for account_id=1 (the fixture account always gets id=1 in a
    fresh DB) so worker-level integration tests don't have to opt in.
    """
    from unittest.mock import MagicMock
    from flowboard.services.flow_client import FlowClient, flow_client
    from flowboard.services.registry import registry

    flow_client._paygate_tier = "PAYGATE_TIER_ONE"

    fc = FlowClient()
    fc._paygate_tier = "PAYGATE_TIER_ONE"
    fake_ws = MagicMock()
    fc.set_extension(fake_ws)
    registry._conns[1] = (fc, fake_ws)

    yield

    flow_client._paygate_tier = None
    registry._conns.pop(1, None)


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

"""Worker dispatches proxy jobs through the registry."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from flowboard.db import get_session
from flowboard.db.models import Account, Board, Node, Request
from flowboard.services.flow_client import FlowClient
from flowboard.services.registry import registry


def _seed_account(email: str) -> int:
    with get_session() as s:
        a = Account(email=email, password_hash="x")
        s.add(a); s.commit(); s.refresh(a)
        return a.id


def _seed_request(account_id: int) -> int:
    with get_session() as s:
        board = Board(name="b", account_id=account_id)
        s.add(board); s.commit(); s.refresh(board)
        node = Node(board_id=board.id, account_id=account_id, short_id="n1", type="image")
        s.add(node); s.commit(); s.refresh(node)
        req = Request(
            node_id=node.id, account_id=account_id, type="proxy",
            params={"url": "https://aisandbox-pa.googleapis.com/v1/test"},
            status="queued",
        )
        s.add(req); s.commit(); s.refresh(req)
        return req.id


@pytest.mark.asyncio
async def test_proxy_fails_extension_offline():
    account_id = _seed_account("offline@example.com")
    req_id = _seed_request(account_id)
    # Ensure no connection is registered for this account (conftest may have
    # seeded account_id=1 via the default-tier fixture — clear it explicitly).
    registry._conns.pop(account_id, None)
    worker = __import__("flowboard.worker.processor", fromlist=["WorkerController"]).WorkerController()
    await worker._process_one(req_id)
    with get_session() as s:
        req = s.get(Request, req_id)
        assert req.status == "failed"
        assert req.error == "extension_offline"


@pytest.mark.asyncio
async def test_proxy_uses_registry_connection():
    account_id = _seed_account("online@example.com")
    req_id = _seed_request(account_id)

    fc = FlowClient()
    fake_ws = MagicMock()
    fake_ws.close = AsyncMock()
    fc.set_extension(fake_ws)
    fc.api_request = AsyncMock(return_value={"status": 200, "data": {"ok": True}})
    registry._conns[account_id] = (fc, fake_ws)

    try:
        worker = __import__("flowboard.worker.processor", fromlist=["WorkerController"]).WorkerController()
        await worker._process_one(req_id)
        fc.api_request.assert_awaited_once()
        with get_session() as s:
            req = s.get(Request, req_id)
            assert req.status == "done"
    finally:
        registry._conns.pop(account_id, None)

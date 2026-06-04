"""Unit tests for ConnectionRegistry.

We don't use real WebSockets — a FakeWs records close calls so we can
verify the last-wins eviction logic without spinning up a server."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from flowboard.services.flow_client import FlowClient
from flowboard.services.registry import ConnectionRegistry


def _fake_ws():
    ws = MagicMock()
    ws.close = AsyncMock()
    return ws


def test_register_returns_flow_client():
    reg = ConnectionRegistry()
    fc = reg.register(1, _fake_ws())
    assert isinstance(fc, FlowClient)


def test_get_returns_registered_client():
    reg = ConnectionRegistry()
    reg.register(1, _fake_ws())
    assert reg.get(1) is not None


def test_get_returns_none_for_unknown_account():
    reg = ConnectionRegistry()
    assert reg.get(999) is None


def test_is_online_true_after_register():
    reg = ConnectionRegistry()
    reg.register(1, _fake_ws())
    assert reg.is_online(1) is True


def test_is_online_false_after_unregister():
    reg = ConnectionRegistry()
    ws = _fake_ws()
    reg.register(1, ws)
    reg.unregister(1, ws)
    assert reg.is_online(1) is False


@pytest.mark.asyncio
async def test_unregister_wrong_ws_does_not_remove():
    """Stale unregister (old ws after reconnect) must not evict the new one."""
    reg = ConnectionRegistry()
    old_ws = _fake_ws()
    new_ws = _fake_ws()
    reg.register(1, old_ws)
    reg.register(1, new_ws)    # last-wins
    reg.unregister(1, old_ws)  # stale — should be no-op
    # Drain eviction task so it doesn't leak
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    assert reg.is_online(1) is True


@pytest.mark.asyncio
async def test_last_wins_closes_old_connection():
    """Second register on the same account closes the first ws with 4408."""
    reg = ConnectionRegistry()
    old_ws = _fake_ws()
    new_ws = _fake_ws()
    reg.register(1, old_ws)
    reg.register(1, new_ws)
    # Drain all pending tasks (the eviction task) completely
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    old_ws.close.assert_awaited_once_with(code=4408, reason="replaced")

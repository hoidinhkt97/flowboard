"""Verify that a job belonging to account A never uses account B's connection."""
from unittest.mock import AsyncMock, MagicMock
from flowboard.services.registry import ConnectionRegistry


def test_registry_returns_none_for_unknown_account():
    reg = ConnectionRegistry()
    assert reg.get(account_id=999) is None


def test_registry_does_not_cross_accounts():
    """Account A's connection must not be returned when looking up account B."""
    reg = ConnectionRegistry()
    mock_ws_a = MagicMock()
    mock_ws_a.close = AsyncMock()

    client_a = reg.register(account_id=1, websocket=mock_ws_a)
    assert client_a is not None

    # B has no connection
    assert reg.get(account_id=2) is None
    # A's connection unaffected
    assert reg.get(account_id=1) is client_a


def test_job_routing_per_account():
    """Simulate worker dispatch: job.account_id determines which connection is used."""
    reg = ConnectionRegistry()
    ws_a = MagicMock()
    ws_a.close = AsyncMock()
    ws_b = MagicMock()
    ws_b.close = AsyncMock()

    reg.register(account_id=1, websocket=ws_a)
    reg.register(account_id=2, websocket=ws_b)

    conn_1 = reg.get(account_id=1)
    conn_2 = reg.get(account_id=2)

    assert conn_1 is not None
    assert conn_2 is not None
    assert conn_1 is not conn_2


def test_unregister_removes_only_correct_account():
    reg = ConnectionRegistry()
    ws_a = MagicMock()
    ws_a.close = AsyncMock()
    ws_b = MagicMock()
    ws_b.close = AsyncMock()

    reg.register(account_id=1, websocket=ws_a)
    reg.register(account_id=2, websocket=ws_b)

    # unregister is synchronous in this implementation
    reg.unregister(account_id=1, websocket=ws_a)

    assert reg.get(account_id=1) is None
    assert reg.get(account_id=2) is not None  # B unaffected

"""Per-account ConnectionRegistry: maps account_id → FlowClient instance.

Lives in-process (Hướng A). Server restart empties the registry; the
extension reconnects automatically via backoff and re-populates it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from flowboard.services.flow_client import FlowClient

logger = logging.getLogger(__name__)

_CLOSE_REPLACED = 4408


class ConnectionRegistry:
    def __init__(self) -> None:
        self._conns: dict[int, tuple[FlowClient, Any]] = {}  # account_id → (fc, ws)

    def register(self, account_id: int, websocket: Any) -> FlowClient:
        """Register websocket for account_id. Last-wins: any existing
        connection is evicted with close code 4408."""
        existing = self._conns.get(account_id)
        if existing is not None:
            old_fc, old_ws = existing
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                asyncio.create_task(
                    old_ws.close(code=_CLOSE_REPLACED, reason="replaced"),
                    name=f"evict-{account_id}",
                )
            old_fc.clear_extension()

        fc = FlowClient()
        fc.set_extension(websocket)
        self._conns[account_id] = (fc, websocket)
        logger.info("registry: account %d connected", account_id)
        return fc

    def unregister(self, account_id: int, websocket: Any) -> None:
        """Remove the connection only if it matches the given websocket.
        A stale unregister (old ws after last-wins eviction) is a no-op."""
        entry = self._conns.get(account_id)
        if entry is None:
            return
        fc, ws = entry
        if ws is not websocket:
            return
        fc.clear_extension()
        del self._conns[account_id]
        logger.info("registry: account %d disconnected", account_id)

    def get(self, account_id: int) -> Optional[FlowClient]:
        entry = self._conns.get(account_id)
        return entry[0] if entry is not None else None

    def is_online(self, account_id: int) -> bool:
        return account_id in self._conns


registry = ConnectionRegistry()

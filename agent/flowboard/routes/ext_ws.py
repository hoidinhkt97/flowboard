"""Authenticated WebSocket endpoint for the Chrome extension.

Extension connects: wss://server/ext?token=<raw_device_token>

Protocol:
1. Hash token → look up DeviceToken → account_id. Bad/revoked → close 4401.
2. registry.register(account_id, ws) — last-wins, evicts stale with 4408.
3. Update DeviceToken.last_seen_at.
4. Message loop → fc.handle_message(data).
5. Disconnect → registry.unregister(account_id, ws).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import DeviceToken
from flowboard.services.registry import registry
from flowboard.services.security import hash_token

logger = logging.getLogger(__name__)
router = APIRouter()

_CLOSE_UNAUTHORIZED = 4401
_PING_INTERVAL_S = 30.0
_PONG_TIMEOUT_S = 10.0


async def _reject(websocket: WebSocket, code: int, reason: str) -> None:
    """Accept then immediately close with an error code so the client sees
    WebSocketDisconnect(code=code). Starlette 0.50 requires accept() before
    close(); simply calling close() without accept() is a no-op on the client."""
    await websocket.accept()
    await websocket.close(code=code, reason=reason)
    raise WebSocketDisconnect(code=code)


@router.websocket("/ext")
async def ext_ws(websocket: WebSocket, token: str = ""):
    if not token:
        await _reject(websocket, _CLOSE_UNAUTHORIZED, "missing token")

    with get_session() as s:
        row = s.exec(
            select(DeviceToken).where(DeviceToken.token_hash == hash_token(token))
        ).first()
        if row is None or row.revoked_at is not None:
            await _reject(websocket, _CLOSE_UNAUTHORIZED, "invalid token")
        account_id = row.account_id
        row.last_seen_at = datetime.now(timezone.utc)
        s.add(row)
        s.commit()

    await websocket.accept()
    fc = registry.register(account_id, websocket)
    logger.info("ext WS: account %d connected", account_id)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_PING_INTERVAL_S
                )
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                    raw = await asyncio.wait_for(
                        websocket.receive_text(), timeout=_PONG_TIMEOUT_S
                    )
                except (asyncio.TimeoutError, WebSocketDisconnect):
                    logger.info("ext WS: account %d heartbeat timeout", account_id)
                    break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("ext WS: invalid JSON from account %d", account_id)
                continue
            try:
                await fc.handle_message(data)
            except Exception:
                logger.exception("ext WS: error for account %d", account_id)
    except WebSocketDisconnect:
        pass
    finally:
        registry.unregister(account_id, websocket)
        logger.info("ext WS: account %d disconnected", account_id)

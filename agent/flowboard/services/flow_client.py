"""Bridge to the Chrome MV3 extension over WebSocket.

Ported + trimmed from flowkit (https://github.com/crisng95/flowkit).

Control flow:
1. Extension opens WS to :9223.
2. Agent sends ``{type:"callback_secret", secret}`` immediately.
3. When the agent wants to make an authenticated call against Google Flow /
   aisandbox-pa, it calls ``flow_client.api_request(url, method, headers, body)``
   which sends ``{id, method:"api_request", params}`` over WS and awaits a future.
4. The extension performs ``fetch(url, Authorization: Bearer <token>)`` inside
   the user's browser session and POSTs the response to
   ``/api/ext/callback`` with ``X-Callback-Secret``.
5. That HTTP handler resolves the pending future by id.
6. WS-side inbound messages from the extension (``token_captured``,
   ``extension_ready``, ``pong``, ``status``) update our stats.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# Google Flow's public API key — appears verbatim in every aisandbox-pa
# request URL Flow web emits. Not a secret; documented here so we don't
# need to plumb it through from the extension on every call.
_FLOW_API_KEY = "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY"
_FLOW_CREDITS_URL = "https://aisandbox-pa.googleapis.com/v1/credits"
# Minimum gap between paygate-tier refreshes when the same Bearer token
# is re-delivered. Tier rarely changes; 60 s is fine for AccountPanel
# freshness and tames the credits-fetch storm an old extension can
# induce by re-emitting `token_captured` on every outbound request.
_TIER_REFRESH_MIN_INTERVAL_S = 60.0


def _approx_body_size(body: Any) -> int:
    """Best-effort byte size of an outbound request body, for logging only.

    Lets a failure log show whether a 413 / timeout correlates with a large
    payload (e.g. a multi-image i2v batch) without dumping the body itself.
    """
    if body is None:
        return 0
    try:
        if isinstance(body, (str, bytes, bytearray)):
            return len(body)
        return len(json.dumps(body))
    except Exception:  # noqa: BLE001
        return -1


def _error_detail(result: Any) -> str:
    """Detailed error summary from a completed api/trpc response.

    The extension returns ``{"status", "data", "error"}``. Transport-level
    failures set top-level ``error``; Flow API errors put a structured body
    on ``data.error`` (``{message, status, details[].reason}``). Mirrors
    ``flow_sdk._extract_inner_api_error`` but lives here so flow_client stays
    import-free of the SDK. Never raises — always returns a str.
    """
    if not isinstance(result, dict):
        return f"<non-dict response: {type(result).__name__}>"
    top = result.get("error")
    if top:
        return str(top)
    data = result.get("data")
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            reasons = [
                d.get("reason")
                for d in (err.get("details") or [])
                if isinstance(d, dict) and isinstance(d.get("reason"), str)
            ]
            msg = err.get("message") or err.get("status") or "API error"
            code = err.get("code")
            prefix = f"[{code}] " if code else ""
            return f"{prefix}{reasons[0]}: {msg}" if reasons else f"{prefix}{msg}"
        # TRPC envelope: result.data.json.result.{status, error}
        inner = data.get("json") if isinstance(data.get("json"), dict) else None
        if isinstance(inner, dict):
            result_inner = inner.get("result") if isinstance(inner.get("result"), dict) else {}
            if isinstance(result_inner, dict):
                err_inner = result_inner.get("error") or result_inner.get("message")
                status_inner = result_inner.get("status")
                if err_inner:
                    return str(err_inner)
                if isinstance(status_inner, int) and status_inner >= 400:
                    return f"TRPC_{status_inner}"
    if isinstance(data, str) and data:
        return data
    status = result.get("status")
    return f"API_{status}"


class FlowClient:
    """Singleton bridge client."""

    DEFAULT_TIMEOUT = 180.0  # seconds

    def __init__(self) -> None:
        self._ws: Optional[Any] = None
        self._pending: dict[str, asyncio.Future] = {}

        self._token_captured_at: Optional[float] = None
        self._flow_key_present: bool = False
        # Cached Bearer token for server-side fetches against
        # aisandbox-pa (e.g. /v1/credits for paygate tier resolution).
        # In-memory only; cleared on extension disconnect. NOT logged
        # anywhere — see fetch_paygate_tier() for the only consumer.
        self._flow_key: Optional[str] = None
        # Last time we hit /v1/credits — guards against the extension
        # emitting `token_captured` on every outbound aisandbox-pa
        # request (polls fire dozens per minute during video gen). The
        # extension was patched to only emit on rotation, but we keep
        # this dedupe so older installs don't spam the credits endpoint.
        self._last_tier_fetch_at: Optional[float] = None
        self._last_logged_key: Optional[str] = None
        # Profile pushed by the extension after it resolves the Bearer
        # token via Google's userinfo endpoint. Stays in-memory only —
        # if the agent restarts the extension will replay it on the
        # next WS reconnect.
        self._user_info: Optional[dict] = None
        # Paygate tier authoritative from /v1/credits + sku for display.
        self._paygate_tier: Optional[str] = None
        self._sku: Optional[str] = None  # e.g. "WS_ULTRA" / "WS_PRO"
        self._credits: Optional[int] = None
        self._request_count = 0
        self._success_count = 0
        self._failed_count = 0
        self._last_error: Optional[str] = None

    # ── connection ─────────────────────────────────────────────────────────
    @property
    def connected(self) -> bool:
        return self._ws is not None

    def set_extension(self, ws: Any) -> None:
        self._ws = ws

    def clear_extension(self) -> None:
        self._ws = None
        self._flow_key_present = False
        self._flow_key = None
        # Drop the cached identity + tier — next reconnect will replay.
        self._user_info = None
        self._paygate_tier = None
        self._sku = None
        self._credits = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("extension_disconnected"))
        self._pending.clear()

    @property
    def user_info(self) -> Optional[dict]:
        return self._user_info

    @property
    def paygate_tier(self) -> Optional[str]:
        return self._paygate_tier

    @property
    def sku(self) -> Optional[str]:
        return self._sku

    @property
    def credits(self) -> Optional[int]:
        return self._credits

    async def fetch_paygate_tier(self) -> bool:
        """Authoritative paygate tier resolution via the official Flow
        /v1/credits endpoint. Replaces the passive request-body sniffer
        as the primary path.

        Triggered automatically when `handle_message` receives a
        `token_captured` message (extension just captured a fresh
        Bearer token), and on demand via /api/auth/scan when the
        cache is cold but the WS is open.

        Returns True on success (tier cached), False otherwise. Failure
        modes:
          - No Bearer token cached (extension hasn't pushed one yet)
          - HTTP 4xx (token expired / revoked)
          - HTTP 5xx / network (transient — caller can retry)
          - Response missing `userPaygateTier` (Flow API contract change)

        IMPORTANT: never log the Bearer token. The error path captures
        only the HTTP status / response shape, never headers.
        """
        if not self._flow_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    _FLOW_CREDITS_URL,
                    params={"key": _FLOW_API_KEY},
                    headers={
                        "authorization": f"Bearer {self._flow_key}",
                        "origin": "https://labs.google",
                        "referer": "https://labs.google/",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning("fetch_paygate_tier transport error: %s", exc)
            return False
        if resp.status_code != 200:
            logger.warning(
                "fetch_paygate_tier returned HTTP %s (token may be expired)",
                resp.status_code,
            )
            return False
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            logger.warning("fetch_paygate_tier: response was not JSON")
            return False
        tier = data.get("userPaygateTier")
        if tier not in ("PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"):
            logger.warning(
                "fetch_paygate_tier: response missing userPaygateTier (got %r)",
                tier,
            )
            return False
        self._paygate_tier = tier
        sku = data.get("sku")
        if isinstance(sku, str):
            self._sku = sku
        credits_val = data.get("credits")
        if isinstance(credits_val, int):
            self._credits = credits_val
        logger.info(
            "fetch_paygate_tier resolved tier=%s sku=%s credits=%s",
            tier, self._sku, self._credits,
        )
        return True

    # ── inbound handling ───────────────────────────────────────────────────
    async def handle_message(self, data: dict) -> None:
        t = data.get("type")
        if t == "extension_ready":
            self._flow_key_present = bool(data.get("flowKeyPresent"))
            logger.info("extension_ready flowKeyPresent=%s", self._flow_key_present)
            return
        if t == "token_captured":
            self._flow_key_present = True
            self._token_captured_at = time.time()
            flow_key = data.get("flowKey")
            if isinstance(flow_key, str) and flow_key:
                key_changed = flow_key != self._flow_key
                self._flow_key = flow_key
                # Defensive dedupe — see _last_tier_fetch_at field comment.
                # Skip the log + credits refetch when the token hasn't
                # rotated and we already fetched within the rate-limit
                # window. Without this, an older extension re-sending the
                # same token on every poll trips one /v1/credits per poll.
                now = time.time()
                last = self._last_tier_fetch_at or 0.0
                if key_changed or (now - last) > _TIER_REFRESH_MIN_INTERVAL_S:
                    if flow_key != self._last_logged_key:
                        logger.info("token_captured (len=%d)", len(flow_key))
                        self._last_logged_key = flow_key
                    self._last_tier_fetch_at = now
                    # Authoritative tier resolution — fetch /v1/credits in
                    # the background so the AccountPanel sees a real tier
                    # within an HTTP RTT instead of waiting for the user's
                    # Flow tab to emit a request the passive sniffer can
                    # see. Don't await: WS handler must stay responsive.
                    asyncio.create_task(self.fetch_paygate_tier())
            return
        if t == "user_info":
            info = data.get("userInfo")
            if isinstance(info, dict):
                # Whitelist on intake — Google's userinfo response can
                # carry id / locale / hd / given_name / family_name etc.
                # The /api/auth/me route filters on output, but caching
                # the full dict here means any future surface that
                # returns flow_client.user_info directly leaks PII.
                # Clamp at the door instead.
                allowed = ("email", "name", "picture", "verified_email")
                self._user_info = {k: info[k] for k in allowed if k in info}
                logger.info(
                    "user_info captured for %s",
                    self._user_info.get("email") or "<no email>",
                )
            return
        if t == "pong":
            return
        # Inbound response (legacy path; production flow uses HTTP callback)
        req_id = data.get("id")
        if req_id and req_id in self._pending:
            self._resolve(req_id, data)

    def resolve_callback(self, data: dict) -> bool:
        """Called by the HTTP callback endpoint after validating the secret.

        Returns True if a pending future matched.
        """
        req_id = data.get("id")
        if not req_id or req_id not in self._pending:
            return False
        self._resolve(req_id, data)
        return True

    def _resolve(self, req_id: str, data: dict) -> None:
        fut = self._pending.pop(req_id, None)
        if not fut or fut.done():
            return
        # Count as failure if (a) an explicit `error` field is set OR
        # (b) the HTTP status is a 4xx/5xx. Otherwise success.
        status = data.get("status")
        http_error = isinstance(status, int) and status >= 400
        explicit_error = bool(data.get("error"))
        if http_error or explicit_error:
            self._failed_count += 1
            # Include the full error text — don't truncate. The actual
            # Google API error message (content-filter reason, quota
            # exceeded, invalid model, etc) is vital for debugging and
            # should appear verbatim in the agent log.
            msg = data.get("error") or f"API_{status}"
            self._last_error = str(msg)
            fut.set_result(data)
        else:
            self._success_count += 1
            fut.set_result(data)

    # ── outbound ──────────────────────────────────────────────────────────
    async def notify(self, message: dict) -> bool:
        """Fire-and-forget WS push to the extension. Returns False when the
        extension isn't connected so callers can surface a meaningful
        diagnostic instead of silently losing the message.

        Used by the logout flow (tell extension to clear its in-memory
        token + cached userinfo) and the scan flow (ask extension to
        re-fetch userinfo when the agent has a connection but the cache
        is empty).
        """
        if not self.connected or self._ws is None:
            return False
        try:
            await self._ws.send_text(json.dumps(message))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("notify failed: %s", exc)
            return False

    async def _send(self, method: str, params: dict, timeout: Optional[float] = None) -> dict:
        if not self.connected:
            return {"error": "extension_disconnected"}

        req_id = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        self._request_count += 1

        payload = {"id": req_id, "method": method, "params": params}
        t0 = time.monotonic()
        try:
            await self._ws.send_text(json.dumps(payload))
            result = await asyncio.wait_for(fut, timeout=timeout or self.DEFAULT_TIMEOUT)
            rt_ms = int((time.monotonic() - t0) * 1000)
            status = result.get("status") if isinstance(result, dict) else None
            has_error = bool(result.get("error")) if isinstance(result, dict) else False
            # An HTTP 4xx/5xx is a failure even when the extension didn't set
            # an explicit top-level `error` (the status + structured error
            # body ride on the envelope). The old log reported `err=False`
            # for a 500 — hiding it. Classify on status too.
            http_error = isinstance(status, int) and status >= 400
            if method in ("api_request", "trpc_request"):
                url = params.get("url", "?")
                path = url.split("/", 3)[-1] if "/" in url else url[:80]
            else:
                path = method
            if has_error or http_error:
                # Detailed failure log for EVERY Flow API round-trip: the
                # HTTP verb, the extracted inner error, and the outbound
                # payload size — enough to triage without grepping the raw
                # envelope. WARNING so it stands out in the agent log.
                logger.warning(
                    "ws_%s ERR: %s %s status=%s detail=%s req_bytes=%d rt=%dms pending=%d",
                    method[:6], params.get("method", "?"), path, status,
                    _error_detail(result), _approx_body_size(params.get("body")),
                    rt_ms, len(self._pending),
                )
            elif method in ("api_request", "trpc_request"):
                logger.info(
                    "ws_%s: %s status=%s err=False rt=%dms pending=%d",
                    method[:6], path, status, rt_ms, len(self._pending),
                )
            return result
        except asyncio.TimeoutError:
            rt_ms = int((time.monotonic() - t0) * 1000)
            self._pending.pop(req_id, None)
            self._failed_count += 1
            self._last_error = "timeout"
            logger.warning("ws_%s: TIMEOUT rt=%dms", method, rt_ms)
            return {"error": "timeout"}
        except ConnectionError as exc:
            self._pending.pop(req_id, None)
            self._failed_count += 1
            self._last_error = str(exc)
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            self._pending.pop(req_id, None)
            self._failed_count += 1
            self._last_error = str(exc)
            return {"error": str(exc)}

    async def api_request(
        self,
        url: str,
        method: str = "POST",
        headers: Optional[dict] = None,
        body: Any = None,
        captcha_action: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        """Proxy an HTTP call against aisandbox-pa.googleapis.com through the
        extension's browser session. If ``captcha_action`` is set, the
        extension solves reCAPTCHA on an active Flow tab before firing the
        fetch and injects the token into the body's recaptchaContext fields.
        """
        params: dict[str, Any] = {
            "url": url,
            "method": method,
            "headers": headers or {},
            "body": body,
        }
        if captcha_action:
            params["captchaAction"] = captcha_action
        return await self._send("api_request", params, timeout=timeout)

    async def trpc_request(
        self,
        url: str,
        method: str = "POST",
        headers: Optional[dict] = None,
        body: Any = None,
        timeout: Optional[float] = 30.0,
    ) -> dict:
        """Proxy a TRPC call against labs.google through the extension.

        No captcha; just Bearer auth passthrough on a `credentials: include`
        fetch. Used for metadata calls like ``project.createProject``.
        """
        return await self._send(
            "trpc_request",
            {"url": url, "method": method, "headers": headers or {}, "body": body},
            timeout=timeout,
        )

    # ── observability ─────────────────────────────────────────────────────
    @property
    def ws_stats(self) -> dict:
        token_age = (
            int(time.time() - self._token_captured_at)
            if self._token_captured_at is not None
            else None
        )
        return {
            "connected": self.connected,
            "flow_key_present": self._flow_key_present,
            "token_age_s": token_age,
            "pending": len(self._pending),
            "request_count": self._request_count,
            "success_count": self._success_count,
            "failed_count": self._failed_count,
            "last_error": self._last_error,
        }


def get_flow_client() -> FlowClient:
    raise RuntimeError(
        "get_flow_client() is deprecated — resolve FlowClient from ConnectionRegistry instead"
    )

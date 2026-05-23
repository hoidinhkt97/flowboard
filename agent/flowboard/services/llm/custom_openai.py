"""Custom OpenAI-compatible provider.

Robust response parsing handles three real-world cases:
  1. Standard JSON body — `resp.json()` works directly
  2. Streaming/SSE body (some proxies return `data: {...}` lines
     even when stream=false) — we collect content from SSE chunks
  3. Wrong Content-Type but valid JSON body — fall back to
     `json.loads(resp.text)` so we don't trip on header quirks

Also explicitly sets `stream: false` in the payload to nudge servers
that default to streaming when the flag is absent.

Lets users plug Flowboard into any OpenAI-compatible endpoint:
- Self-hosted models via LM Studio / Ollama / vLLM / TGI
- API gateways: OpenRouter, Together.ai, Groq, Fireworks, DeepInfra
- Azure OpenAI (with custom base URL)
- Enterprise OpenAI proxies behind a reverse charge

The provider has no CLI. Configuration lives entirely in secrets:
- ``apiKeys.custom_openai`` — bearer token sent as Authorization header
- ``providerConfig.custom_openai.url`` — base URL ending at /v1 (no trailing slash)
- ``providerConfig.custom_openai.model`` — model id to request

Endpoint contract: POST {url}/chat/completions with OpenAI chat schema.
Vision (image attachments) is announced as supported because most modern
OpenAI-compatible servers accept image_url content blocks. If the user's
endpoint doesn't, attachments simply degrade to an HTTP error from the
remote server — surfaced as LLMError so it lands in the Settings test row.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import time
from pathlib import Path
from typing import Optional

import httpx

from .base import LLMError
from . import secrets

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 90.0
_AVAILABILITY_TTL_S = 60.0
_MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
_DEFAULT_MODEL = "gpt-4o-mini"


class CustomOpenAIProvider:
    """OpenAI-compatible REST provider. Conforms to ``LLMProvider``."""

    name: str = "custom_openai"
    supports_vision: bool = True  # depends on endpoint; we declare true and let HTTP errors surface

    def __init__(self) -> None:
        self._cached_at: Optional[float] = None
        self._cached_value: Optional[bool] = None

    def reset_cache(self) -> None:
        """Called after config change so the next /providers list reflects it."""
        self._cached_at = None
        self._cached_value = None

    @property
    def mode(self) -> str:
        """Always 'api' — no CLI path. Surfaced by /api/llm/providers."""
        return "api"

    # ── availability ──────────────────────────────────────────────────

    async def is_available(self) -> bool:
        """True when both API key AND URL are configured.

        We don't ping the endpoint here — that costs latency on every
        Settings panel poll. Test button is the explicit verification.
        """
        now = time.monotonic()
        if (
            self._cached_value is not None
            and self._cached_at is not None
            and now - self._cached_at < _AVAILABILITY_TTL_S
        ):
            return self._cached_value
        key = secrets.get_api_key("custom_openai")
        cfg = secrets.get_provider_config("custom_openai")
        url = cfg.get("url") if isinstance(cfg, dict) else None
        ok = bool(key) and bool(url)
        self._cached_value = ok
        self._cached_at = now
        return ok

    # ── dispatch ──────────────────────────────────────────────────────

    async def run(
        self,
        user_prompt: str,
        *,
        system_prompt: Optional[str] = None,
        attachments: Optional[list[str]] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        model: Optional[str] = None,
    ) -> str:
        key = secrets.get_api_key("custom_openai")
        cfg = secrets.get_provider_config("custom_openai") or {}
        base_url = cfg.get("url")

        if not key:
            raise LLMError("Custom OpenAI API key not configured")
        if not base_url:
            raise LLMError("Custom OpenAI URL not configured")

        chosen_model = model or cfg.get("model") or _DEFAULT_MODEL

        # Build OpenAI chat messages
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if attachments:
            content: list[dict] = [{"type": "text", "text": user_prompt}]
            for path in attachments:
                content.append(_image_url_block(path))
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_prompt})

        endpoint = base_url.rstrip("/") + "/chat/completions"
        # stream=false explicitly — some proxies default to streaming
        payload = {"model": chosen_model, "messages": messages, "stream": False}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    endpoint,
                    headers={
                        "authorization": f"Bearer {key}",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise LLMError(f"custom_openai request timed out after {timeout}s") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"custom_openai transport error: {exc}") from exc

        if resp.status_code != 200:
            raise LLMError(
                f"HTTP {resp.status_code} from {endpoint}: {_safe_error_message(resp)}"
            )

        content = _extract_content(resp, endpoint)
        if not content:
            raise LLMError(
                f"Empty content from {endpoint}. Body: {resp.text[:300]!r}"
            )
        return content


# ── helpers ────────────────────────────────────────────────────────────

def _extract_content(resp: httpx.Response, endpoint: str) -> str:
    """Extract chat-completion content from the response.

    Tries in order:
      1. Standard `resp.json()` (most servers)
      2. `json.loads(resp.text)` (servers with wrong Content-Type)
      3. SSE/streaming parse — concatenate `data: {...}` chunks (some
         proxies return SSE even when stream=false in the request)
    """
    # Try 1 + 2: plain JSON
    data = None
    for parser in (resp.json, lambda: json.loads(resp.text)):
        try:
            data = parser()
            break
        except (ValueError, json.JSONDecodeError):
            data = None

    if isinstance(data, dict):
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                f"Response missing choices[0].message.content. Body: {str(data)[:300]}"
            ) from exc

    # Try 3: SSE streaming response
    text = resp.text or ""
    if "data:" in text:
        parts: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if chunk == "[DONE]" or not chunk:
                continue
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            try:
                delta = obj["choices"][0].get("delta") or {}
                msg = obj["choices"][0].get("message") or {}
                piece = delta.get("content") or msg.get("content") or ""
                if isinstance(piece, str):
                    parts.append(piece)
            except (KeyError, IndexError, TypeError):
                continue
        if parts:
            return "".join(parts)

    body_snippet = text[:300].replace("\n", " ")
    raise LLMError(
        f"Could not parse response from {endpoint}. "
        f"Expected OpenAI chat completion JSON or SSE stream. "
        f"Body: {body_snippet!r}"
    )


def _image_url_block(path: str) -> dict:
    p = Path(path)
    size = p.stat().st_size
    if size > _MAX_ATTACHMENT_BYTES:
        raise LLMError(
            f"attachment too large for custom_openai: "
            f"{size // (1024 * 1024)}MB > 5MB cap"
        )
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"},
    }


def _safe_error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return "(non-JSON body)"
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str):
                return msg[:200]
        msg = body.get("message")
        if isinstance(msg, str):
            return msg[:200]
    return "(unrecognised body)"

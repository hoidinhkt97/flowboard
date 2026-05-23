"""Custom OpenAI-compatible provider.

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
        payload = {"model": chosen_model, "messages": messages}

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
                f"custom_openai HTTP {resp.status_code}: {_safe_error_message(resp)}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMError("custom_openai response was not JSON") from exc
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"custom_openai response missing content: {data!r:.200}") from exc


# ── helpers ────────────────────────────────────────────────────────────

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

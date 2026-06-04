"""Direct-API LLM providers (no CLI subprocess).

Each class accepts an api_key at construction and implements LLMProvider.
Used for per-user API key dispatch via make_account_provider().
Constructed fresh per run_llm call — no global state.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from .base import LLMError, LLMProvider

if TYPE_CHECKING:
    from flowboard.db.models import Account

logger = logging.getLogger(__name__)


class AnthropicApiProvider:
    name = "claude_api"
    supports_vision = True

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def run(
        self,
        user_prompt: str,
        *,
        system_prompt: Optional[str] = None,
        attachments: Optional[list[str]] = None,
        timeout: float = 90.0,
    ) -> str:
        import anthropic

        def _call() -> str:
            client = anthropic.Anthropic(api_key=self._api_key)
            kwargs: dict = {
                "model": "claude-sonnet-4-6",
                "max_tokens": 8096,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            msg = client.messages.create(**kwargs)
            return msg.content[0].text

        try:
            return await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
        except anthropic.AuthenticationError as exc:
            raise LLMError(f"Anthropic API key invalid: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Anthropic API error: {exc}") from exc


class GeminiApiProvider:
    name = "gemini_api"
    supports_vision = True

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def run(
        self,
        user_prompt: str,
        *,
        system_prompt: Optional[str] = None,
        attachments: Optional[list[str]] = None,
        timeout: float = 90.0,
    ) -> str:
        def _call() -> str:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(
                "gemini-2.5-flash",
                system_instruction=system_prompt or "",
            )
            response = model.generate_content(user_prompt)
            return response.text

        try:
            return await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini API error: {exc}") from exc


class OpenAIApiProvider:
    name = "openai_api"
    supports_vision = True

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def run(
        self,
        user_prompt: str,
        *,
        system_prompt: Optional[str] = None,
        attachments: Optional[list[str]] = None,
        timeout: float = 90.0,
    ) -> str:
        def _call() -> str:
            import openai
            client = openai.OpenAI(api_key=self._api_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
            )
            return completion.choices[0].message.content

        try:
            return await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"OpenAI API error: {exc}") from exc


def make_account_provider(account: "Account") -> Optional[LLMProvider]:
    """Return an API-backed LLM provider for this account, or None if not configured."""
    if not account.llm_provider or not account.llm_api_key_enc:
        return None

    from flowboard.services.security import decrypt_secret
    try:
        api_key = decrypt_secret(account.llm_api_key_enc)
    except Exception:
        logger.warning("Failed to decrypt LLM API key for account %s", account.id)
        return None

    provider_map: dict[str, type] = {
        "claude": AnthropicApiProvider,
        "gemini": GeminiApiProvider,
        "openai": OpenAIApiProvider,
    }
    cls = provider_map.get(account.llm_provider)
    if cls is None:
        return None
    return cls(api_key=api_key)

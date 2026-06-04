"""Account LLM settings — GET/PATCH /api/account/settings."""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Account
from flowboard.deps import get_current_account
from flowboard.services import security
from flowboard.services.llm.base import LLMError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/account", tags=["account"])

LLMProviderName = Literal["claude", "gemini", "openai"]


class SettingsResponse(BaseModel):
    llm_provider: Optional[str]
    llm_api_key_configured: bool


class SettingsPatch(BaseModel):
    llm_provider: LLMProviderName
    llm_api_key: str

    @field_validator("llm_api_key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("API key must not be empty")
        return stripped


async def _validate_api_key(provider: str, api_key: str) -> None:
    """Make a minimal test call to verify the key works. Raises LLMError on failure."""
    if provider == "claude":
        def _check() -> None:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
        try:
            await asyncio.to_thread(_check)
        except Exception as exc:
            raise LLMError(f"Invalid Anthropic API key: {exc}") from exc

    elif provider == "gemini":
        def _check() -> None:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            model.generate_content("hi", generation_config={"max_output_tokens": 1})
        try:
            await asyncio.to_thread(_check)
        except Exception as exc:
            raise LLMError(f"Invalid Gemini API key: {exc}") from exc

    elif provider == "openai":
        def _check() -> None:
            import openai
            client = openai.OpenAI(api_key=api_key)
            client.models.list()
        try:
            await asyncio.to_thread(_check)
        except Exception as exc:
            raise LLMError(f"Invalid OpenAI API key: {exc}") from exc


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(acct: Account = Depends(get_current_account)):
    return SettingsResponse(
        llm_provider=acct.llm_provider,
        llm_api_key_configured=bool(acct.llm_api_key_enc),
    )


@router.patch("/settings", response_model=SettingsResponse)
async def patch_settings(
    body: SettingsPatch,
    acct: Account = Depends(get_current_account),
):
    try:
        result = _validate_api_key(body.llm_provider, body.llm_api_key)
        # Support both async (real) and sync (monkeypatched in tests) callables
        if inspect.isawaitable(result):
            await result
    except LLMError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    encrypted = security.encrypt_secret(body.llm_api_key)

    with get_session() as s:
        db_acct = s.exec(select(Account).where(Account.id == acct.id)).first()
        db_acct.llm_provider = body.llm_provider
        db_acct.llm_api_key_enc = encrypted
        s.add(db_acct)
        s.commit()

    return SettingsResponse(
        llm_provider=body.llm_provider,
        llm_api_key_configured=True,
    )

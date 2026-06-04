"""Unit tests for direct-API LLM providers."""
import pytest
from unittest.mock import MagicMock, patch

from flowboard.services.llm.api_providers import (
    AnthropicApiProvider,
    GeminiApiProvider,
    OpenAIApiProvider,
    make_account_provider,
)
from flowboard.services.llm.base import LLMError


def test_provider_names():
    assert AnthropicApiProvider("k").name == "claude_api"
    assert GeminiApiProvider("k").name == "gemini_api"
    assert OpenAIApiProvider("k").name == "openai_api"


@pytest.mark.asyncio
async def test_providers_available_with_key():
    assert await AnthropicApiProvider("sk-ant-x").is_available() is True
    assert await GeminiApiProvider("AIzaX").is_available() is True
    assert await OpenAIApiProvider("sk-x").is_available() is True


@pytest.mark.asyncio
async def test_providers_unavailable_without_key():
    assert await AnthropicApiProvider("").is_available() is False
    assert await GeminiApiProvider("").is_available() is False
    assert await OpenAIApiProvider("").is_available() is False


@pytest.mark.asyncio
async def test_anthropic_provider_run():
    p = AnthropicApiProvider(api_key="sk-ant-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="hello from claude")]
    )
    with patch("anthropic.Anthropic", return_value=mock_client):
        result = await p.run("say hello")
    assert result == "hello from claude"
    mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_gemini_provider_run():
    p = GeminiApiProvider(api_key="AIzaTest")
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text="hello from gemini")
    with patch("google.generativeai.GenerativeModel", return_value=mock_model), \
         patch("google.generativeai.configure"):
        result = await p.run("say hello")
    assert result == "hello from gemini"


@pytest.mark.asyncio
async def test_openai_provider_run():
    p = OpenAIApiProvider(api_key="sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="hello from openai"))]
    )
    with patch("openai.OpenAI", return_value=mock_client):
        result = await p.run("say hello")
    assert result == "hello from openai"


@pytest.mark.asyncio
async def test_anthropic_raises_llm_error_on_auth_failure():
    p = AnthropicApiProvider(api_key="bad-key")
    with patch("anthropic.Anthropic") as mock_cls:
        import anthropic
        mock_cls.return_value.messages.create.side_effect = anthropic.AuthenticationError(
            message="invalid key", response=MagicMock(), body={}
        )
        with pytest.raises(LLMError):
            await p.run("test")


def test_make_account_provider_returns_none_without_key():
    from flowboard.db.models import Account
    acct = Account(id=1, email="a@b.com", password_hash="x")
    assert make_account_provider(acct) is None


def test_make_account_provider_returns_anthropic(monkeypatch):
    from flowboard.db.models import Account
    from flowboard.services import security
    monkeypatch.setattr(security, "decrypt_secret", lambda b: "sk-ant-real")
    acct = Account(id=1, email="a@b.com", password_hash="x",
                   llm_provider="claude", llm_api_key_enc=b"encrypted")
    provider = make_account_provider(acct)
    assert isinstance(provider, AnthropicApiProvider)


def test_make_account_provider_returns_gemini(monkeypatch):
    from flowboard.db.models import Account
    from flowboard.services import security
    monkeypatch.setattr(security, "decrypt_secret", lambda b: "AIzaReal")
    acct = Account(id=1, email="a@b.com", password_hash="x",
                   llm_provider="gemini", llm_api_key_enc=b"encrypted")
    provider = make_account_provider(acct)
    assert isinstance(provider, GeminiApiProvider)


def test_make_account_provider_returns_openai(monkeypatch):
    from flowboard.db.models import Account
    from flowboard.services import security
    monkeypatch.setattr(security, "decrypt_secret", lambda b: "sk-real")
    acct = Account(id=1, email="a@b.com", password_hash="x",
                   llm_provider="openai", llm_api_key_enc=b"encrypted")
    provider = make_account_provider(acct)
    assert isinstance(provider, OpenAIApiProvider)

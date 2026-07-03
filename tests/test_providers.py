from __future__ import annotations

import pytest

from spyv import provider
from spyv.providers import LLMClient
from spyv.providers.base import (
    MissingCredentialError,
    ProviderError,
)
from spyv.providers.factory import SUPPORTED, auto


def test_unknown_provider_raises():
    with pytest.raises(ProviderError, match="Unknown provider"):
        provider("nonsense")


def test_openai_compat_requires_base_url():
    with pytest.raises(ProviderError, match="base_url"):
        provider("openai-compat", model="llama-3.1")


def test_openai_compat_requires_model():
    with pytest.raises(ProviderError, match="model"):
        provider("openai-compat", base_url="http://localhost:8000/v1")


def test_local_provider_requires_model():
    with pytest.raises(ProviderError, match="model"):
        provider("vllm")


def test_openai_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(MissingCredentialError):
        provider("openai", model="gpt-4o")


def test_anthropic_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingCredentialError):
        provider("anthropic", model="claude-sonnet-5")


def test_gemini_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(MissingCredentialError):
        provider("gemini", model="gemini-2.0-flash")


def test_auto_raises_when_no_key(monkeypatch):
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ProviderError, match="no provider key"):
        auto()


def test_auto_prefers_openai_when_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = auto(model="gpt-4o")
    assert isinstance(client, LLMClient)
    assert client.model == "gpt-4o"


def test_openai_compat_builds_with_base_url_and_no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = provider("vllm", model="llama-3.1-70b")
    assert isinstance(client, LLMClient)
    assert client.model == "llama-3.1-70b"


def test_supported_list_contains_core_providers():
    for name in ("openai", "anthropic", "gemini", "vllm", "ollama"):
        assert name in SUPPORTED


def test_adapters_satisfy_llmclient_protocol(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = provider("openai", model="gpt-4o")
    assert hasattr(client, "chat_completion")
    assert isinstance(client, LLMClient)

from __future__ import annotations

import os

from .adapters import (
    AnthropicAdapter,
    GeminiAdapter,
    OpenAIAdapter,
    OpenAICompatAdapter,
)
from .base import LLMClient, ProviderError

_LOCAL_DEFAULTS = {
    "vllm": "http://localhost:8000/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "tgi": "http://localhost:8080/v1",
}

_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-2.0-flash",
}

SUPPORTED = ("openai", "anthropic", "gemini", "vllm", "ollama", "lmstudio", "tgi", "openai-compat")


def provider(
    name: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMClient:
    key = name.lower().strip()

    if key == "openai":
        return OpenAIAdapter(model or _DEFAULT_MODELS["openai"], api_key=api_key, base_url=base_url)

    if key == "anthropic":
        return AnthropicAdapter(model or _DEFAULT_MODELS["anthropic"], api_key=api_key)

    if key == "gemini":
        return GeminiAdapter(model or _DEFAULT_MODELS["gemini"], api_key=api_key)

    if key in _LOCAL_DEFAULTS:
        resolved_url = base_url or _LOCAL_DEFAULTS[key]
        if not model:
            raise ProviderError(f"Provider '{key}' requires an explicit model name.")
        return OpenAICompatAdapter(model, base_url=resolved_url, api_key=api_key)

    if key == "openai-compat":
        if not base_url:
            raise ProviderError("Provider 'openai-compat' requires base_url.")
        if not model:
            raise ProviderError("Provider 'openai-compat' requires an explicit model name.")
        return OpenAICompatAdapter(model, base_url=base_url, api_key=api_key)

    raise ProviderError(
        f"Unknown provider '{name}'. Supported: {', '.join(SUPPORTED)}."
    )


def auto(*, model: str | None = None) -> LLMClient:
    if os.environ.get("OPENAI_API_KEY"):
        return provider("openai", model=model)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return provider("anthropic", model=model)
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return provider("gemini", model=model)
    raise ProviderError(
        "auto() found no provider key in the environment. "
        "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY, "
        "or call provider(...) explicitly."
    )

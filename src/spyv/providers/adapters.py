from __future__ import annotations

import os

from .base import MissingCredentialError, MissingDependencyError


class OpenAIAdapter:
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        try:
            import openai
        except ImportError as exc:
            raise MissingDependencyError(
                "OpenAIAdapter requires the 'openai' package. "
                "Install with: pip install 'spyv[openai]'"
            ) from exc
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key and base_url is None:
            raise MissingCredentialError("OPENAI_API_KEY is not set.")
        self.model = model
        self._client = openai.OpenAI(api_key=key or "not-needed", base_url=base_url)

    def chat_completion(
        self, *, model: str, system: str, user: str, temperature: float = 0.0
    ) -> str:
        response = self._client.chat.completions.create(
            model=model or self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""


class AnthropicAdapter:
    def __init__(self, model: str, *, api_key: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise MissingDependencyError(
                "AnthropicAdapter requires the 'anthropic' package. "
                "Install with: pip install 'spyv[anthropic]'"
            ) from exc
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise MissingCredentialError("ANTHROPIC_API_KEY is not set.")
        self.model = model
        self._client = anthropic.Anthropic(api_key=key)

    def chat_completion(
        self, *, model: str, system: str, user: str, temperature: float = 0.0
    ) -> str:
        response = self._client.messages.create(
            model=model or self.model,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=4096,
        )
        parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        return "".join(parts)


class GeminiAdapter:
    def __init__(self, model: str, *, api_key: str | None = None) -> None:
        try:
            from google import genai
        except ImportError as exc:
            raise MissingDependencyError(
                "GeminiAdapter requires the 'google-genai' package. "
                "Install with: pip install 'spyv[gemini]'"
            ) from exc
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise MissingCredentialError("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set.")
        self.model = model
        self._genai = genai
        self._client = genai.Client(api_key=key)

    def chat_completion(
        self, *, model: str, system: str, user: str, temperature: float = 0.0
    ) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=model or self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
            ),
        )
        return response.text or ""


class OpenAICompatAdapter(OpenAIAdapter):
    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model, api_key=api_key or "local", base_url=base_url)

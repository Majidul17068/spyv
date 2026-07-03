from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def chat_completion(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.0,
    ) -> str: ...


class ProviderError(RuntimeError):
    pass


class MissingDependencyError(ProviderError):
    pass


class MissingCredentialError(ProviderError):
    pass

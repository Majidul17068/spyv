from __future__ import annotations

import asyncio
import json as _json
import logging
import sys
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from rich.text import Text

from ..checkers import CheckerHit, run_checkers
from ..terminal import _resolve_console
from .watch import _now_iso, _resolve_output_mode

F = TypeVar("F", bound=Callable[..., Any])

_logger = logging.getLogger("spyv.guard")

_SEVERITY_STYLE = {
    "critical": "bold white on red",
    "high": "red",
    "medium": "yellow",
    "low": "green",
    "info": "grey50",
}


class GuardBreach(Exception):
    def __init__(self, label: str, hits: list[CheckerHit]) -> None:
        self.label = label
        self.hits = hits
        joined = ", ".join(f"{h.checker}/{h.label}" for h in hits)
        super().__init__(f"spyv.guard blocked {label!r}: {joined}")


def _redact(evidence: str) -> str:
    if len(evidence) <= 8:
        return "***"
    return f"{evidence[:3]}***{evidence[-2:]}"


def _extract_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    for attr in ("content", "text", "output_text"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
    choices = getattr(result, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
    if isinstance(result, dict):
        for key in ("content", "text", "output", "response", "message", "answer"):
            value = result.get(key)
            if isinstance(value, str):
                return value
    return str(result)


def _emit(label: str, hits: list[CheckerHit], redact: bool) -> None:
    mode = _resolve_output_mode()
    if mode in ("pretty", "both"):
        console = _resolve_console(color=None)
        line = Text()
        line.append("◆ ", style="grey50")
        line.append("spyv.guard  ", style="#7c3aed")
        line.append(label, style="bold")
        line.append("  BREACH ", style="bold white on red")
        for h in hits:
            ev = _redact(h.evidence) if redact else h.evidence
            line.append(f" [{h.severity}] {h.checker}/{h.label}={ev}", style=_SEVERITY_STYLE.get(h.severity, "white"))
        console.print(line)
    if mode in ("json", "both"):
        payload = {
            "event": "guard",
            "label": label,
            "breach": True,
            "hits": [
                {
                    "checker": h.checker,
                    "label": h.label,
                    "severity": h.severity,
                    "evidence": _redact(h.evidence) if redact else h.evidence,
                }
                for h in hits
            ],
            "ts": _now_iso(),
        }
        line = _json.dumps(payload, ensure_ascii=False, default=str)
        print(line, file=sys.stderr, flush=True)
        _logger.warning(line)


def _label_of(fn: Callable[..., Any], override: str | None) -> str:
    if override:
        return override
    return getattr(fn, "__qualname__", None) or getattr(fn, "__name__", "anonymous")


def guard(
    fn: F | None = None,
    *,
    system_prompt: str = "",
    on_breach: str = "warn",
    extract: Callable[[Any], str] | None = None,
    redact: bool = True,
    label: str | None = None,
) -> Any:
    def _decorate(target: F) -> F:
        resolved_label = _label_of(target, label)
        pull = extract or _extract_text

        def _check(result: Any) -> Any:
            hits = run_checkers(system_prompt, pull(result))
            if hits:
                _emit(resolved_label, hits, redact)
                if on_breach == "raise":
                    raise GuardBreach(resolved_label, hits)
            return result

        if asyncio.iscoroutinefunction(target):
            @wraps(target)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return _check(await target(*args, **kwargs))

            return _async_wrapper  # type: ignore[return-value]

        @wraps(target)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return _check(target(*args, **kwargs))

        return _sync_wrapper  # type: ignore[return-value]

    if fn is not None and callable(fn):
        return _decorate(fn)
    return _decorate


__all__ = ["GuardBreach", "guard"]

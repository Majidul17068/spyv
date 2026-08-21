from __future__ import annotations

import asyncio
import json as _json
import logging
import sys
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from rich.text import Text

from ..checkers import CheckerHit, run_checkers
from ..policy import PolicyRule, PolicyViolation, ToolCall, evaluate, load_rules
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
    def __init__(
        self,
        label: str,
        hits: list[CheckerHit],
        violations: list[PolicyViolation] | None = None,
    ) -> None:
        self.label = label
        self.hits = hits
        self.violations = violations or []
        parts = [f"{h.checker}/{h.label}" for h in hits]
        parts += [f"{v.rule_id}({v.tool})" for v in self.violations]
        super().__init__(f"spyv.guard blocked {label!r}: {', '.join(parts)}")


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


def _coerce_arguments(value: Any) -> dict[str, Any]:
    """Tool arguments arrive as a dict or as a JSON string, depending on provider."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = _json.loads(value)
        except (ValueError, TypeError):
            return {"_raw": value}
        return parsed if isinstance(parsed, dict) else {"_value": parsed}
    return {}


def _one_tool_call(item: Any) -> ToolCall | None:
    """Normalize a single tool call from the shapes real SDKs return."""
    # OpenAI: item.function.name / item.function.arguments (a JSON string)
    function = getattr(item, "function", None)
    if function is None and isinstance(item, dict):
        function = item.get("function")
    if function is not None:
        name = getattr(function, "name", None)
        if name is None and isinstance(function, dict):
            name = function.get("name")
        arguments = getattr(function, "arguments", None)
        if arguments is None and isinstance(function, dict):
            arguments = function.get("arguments")
        if name:
            return ToolCall(name=str(name), arguments=_coerce_arguments(arguments))

    # Anthropic tool_use blocks: .name / .input
    name = getattr(item, "name", None)
    arguments = getattr(item, "input", None)
    if arguments is None:
        arguments = getattr(item, "arguments", None)
    if isinstance(item, dict):
        name = name or item.get("name") or item.get("tool")
        if arguments is None:
            arguments = item.get("input", item.get("arguments"))
    if name:
        return ToolCall(name=str(name), arguments=_coerce_arguments(arguments))
    return None


def _extract_tool_calls(result: Any) -> list[ToolCall]:
    """Best-effort tool-call extraction, in call order.

    Deliberately tolerant: an agent framework that returns an unfamiliar shape
    should degrade to "no tool calls observed" rather than raise inside the
    decorator wrapping someone's production function.
    """
    raw: Any = None

    choices = getattr(result, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        raw = getattr(message, "tool_calls", None)

    if raw is None:
        raw = getattr(result, "tool_calls", None)

    if raw is None and isinstance(result, dict):
        raw = result.get("tool_calls")
        if raw is None:
            choices_d = result.get("choices")
            if isinstance(choices_d, list) and choices_d:
                first = choices_d[0]
                if isinstance(first, dict):
                    message_d = first.get("message") or {}
                    if isinstance(message_d, dict):
                        raw = message_d.get("tool_calls")

    # Anthropic-style content blocks
    if raw is None:
        content = getattr(result, "content", None)
        if content is None and isinstance(result, dict):
            content = result.get("content")
        if isinstance(content, list):
            blocks = []
            for block in content:
                kind = getattr(block, "type", None)
                if kind is None and isinstance(block, dict):
                    kind = block.get("type")
                if kind == "tool_use":
                    blocks.append(block)
            raw = blocks or None

    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]

    calls: list[ToolCall] = []
    for item in raw:
        call = _one_tool_call(item)
        if call is not None:
            calls.append(call)
    return calls


def _resolve_policy(policy: Any) -> list[PolicyRule]:
    if policy is None:
        return []
    if isinstance(policy, (str, Path)):
        return load_rules(policy)
    if isinstance(policy, dict):
        return load_rules(policy)
    return [r if isinstance(r, PolicyRule) else PolicyRule(**r) for r in policy]


def _emit(
    label: str,
    hits: list[CheckerHit],
    redact: bool,
    violations: list[PolicyViolation] | None = None,
) -> None:
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
        for v in violations or []:
            line.append(
                f" [{v.severity}] policy/{v.rule_id} {v.tool}",
                style=_SEVERITY_STYLE.get(v.severity, "white"),
            )
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
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "kind": v.kind,
                    "severity": v.severity,
                    "tool": v.tool,
                    "call_index": v.call_index,
                    "message": v.message,
                    "evidence": _redact(v.evidence) if (redact and v.evidence) else v.evidence,
                }
                for v in violations or []
            ],
            "ts": _now_iso(),
        }
        line = _json.dumps(payload, ensure_ascii=False, default=str)
        # Emit exactly once. When the application has configured logging, route
        # through it so the event reaches the app's handlers; otherwise write to
        # stderr directly. Doing both meant a breach was recorded twice, which
        # double-counts in any log-based alerting.
        if _logger.handlers or logging.getLogger().handlers:
            _logger.warning(line)
        else:
            print(line, file=sys.stderr, flush=True)


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
    policy: Any = None,
    context: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
    extract_tool_calls: Callable[[Any], list[ToolCall]] | None = None,
) -> Any:
    """Observe a real agent call and check it deterministically.

    Two independent checks run on what actually happened:

      output      the existing regex checkers over the returned text -- secrets,
                  personal data, verbatim system-prompt leakage.
      tool calls  the tool-call policy, if one is supplied. This is the half no
                  static analyzer can reach: a prompt built at runtime is
                  invisible to source analysis, but the call it produced is not.

    `policy` accepts a list of PolicyRule, a mapping, or a path to a YAML file.
    `context` supplies the authorization markers require_auth rules read, either
    as a dict or as a callable evaluated per call (for a request-scoped value).
    """
    rules = _resolve_policy(policy)

    def _decorate(target: F) -> F:
        resolved_label = _label_of(target, label)
        pull = extract or _extract_text
        pull_calls = extract_tool_calls or _extract_tool_calls

        def _check(result: Any) -> Any:
            hits = run_checkers(system_prompt, pull(result))

            violations: list[PolicyViolation] = []
            if rules:
                # A malformed provider payload must not take down the caller's
                # function, so extraction failure degrades to "nothing observed".
                try:
                    calls = pull_calls(result)
                # Observation must never break the call it is observing.
                except Exception:
                    calls = []
                if calls:
                    ctx = context() if callable(context) else context
                    violations = evaluate(calls, rules, context=ctx).violations

            if hits or violations:
                _emit(resolved_label, hits, redact, violations)
                if on_breach == "raise":
                    raise GuardBreach(resolved_label, hits, violations)
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

"""Deterministic tool-call policy.

Static analysis can only say a prompt *permits* something. This module checks
what an agent *did*: which tools it called, in what order, with what arguments.
No model is consulted, so a violation is a fact rather than a judgement -- which
is the whole point (see SPYV-VERDICT-AND-PLAN T6).

Six rule kinds, deliberately bounded. Each answers a question an operator can
actually be held to:

  deny                    this tool must never be called
  arg_limit               a numeric argument must not exceed a hard cap
  require_confirmation    a destructive call must be preceded by a confirmation,
                          optionally only once an argument crosses a threshold
  require_auth            a call requires an authorization marker in context
  require_precedes        one tool must be called before another (read before
                          write, check balance before transfer)
  no_secret_in_arguments  arguments must not carry credentials or personal data

Rules are data, so they live in YAML next to the code they govern and a reviewer
can read the policy without reading Python.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..checkers import run_checkers

RuleKind = Literal[
    "deny",
    "arg_limit",
    "require_confirmation",
    "require_auth",
    "require_precedes",
    "no_secret_in_arguments",
]

Severity = Literal["info", "low", "medium", "high", "critical"]


class ToolCall(BaseModel):
    """One observed tool invocation. Order in the list is call order."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    def arg_number(self, key: str) -> float | None:
        """Numeric value of an argument, tolerating strings like '1200' or '1,200.50'."""
        value = self.arguments.get(key)
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace(",", "").replace("$", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None


class PolicyRule(BaseModel):
    id: str
    kind: RuleKind
    severity: Severity = "high"
    description: str = ""

    # which tools the rule governs; `tool` is sugar for a single-entry `tools`
    tool: str | None = None
    tools: list[str] = Field(default_factory=list)

    # arg_limit / require_confirmation
    arg: str | None = None
    max_value: float | None = None
    when_arg_over: float | None = None

    # require_confirmation
    confirmation_tools: list[str] = Field(default_factory=list)

    # require_auth
    auth_marker: str = "authorized"

    # require_precedes
    first: str | None = None
    then: str | None = None

    def governs(self) -> set[str]:
        names = set(self.tools)
        if self.tool:
            names.add(self.tool)
        return names


class PolicyViolation(BaseModel):
    rule_id: str
    kind: RuleKind
    severity: Severity
    tool: str
    call_index: int
    message: str
    evidence: str = ""


class PolicyResult(BaseModel):
    n_calls: int
    n_rules: int
    violations: list[PolicyViolation] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def worst_severity(self) -> Severity:
        rank = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        worst: Severity = "info"
        for v in self.violations:
            if rank[v.severity] > rank[worst]:
                worst = v.severity
        return worst


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def load_rules(source: str | Path | dict[str, Any]) -> list[PolicyRule]:
    """Load rules from a YAML/JSON file path, or from an already-parsed mapping."""
    if isinstance(source, dict):
        data = source
    else:
        import yaml

        text = Path(source).read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
    raw = data.get("rules", []) if isinstance(data, dict) else []
    if not isinstance(raw, list):
        raise ValueError("policy 'rules' must be a list")
    return [PolicyRule(**item) for item in raw]


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------
def _serialize_args(call: ToolCall) -> str:
    try:
        return json.dumps(call.arguments, default=str)
    except (TypeError, ValueError):
        return str(call.arguments)


def _check_deny(rule: PolicyRule, calls: list[ToolCall]) -> list[PolicyViolation]:
    governed = rule.governs()
    out: list[PolicyViolation] = []
    for i, call in enumerate(calls):
        if call.name in governed:
            out.append(
                PolicyViolation(
                    rule_id=rule.id,
                    kind=rule.kind,
                    severity=rule.severity,
                    tool=call.name,
                    call_index=i,
                    message=f"{call.name} is denied by policy but was called.",
                )
            )
    return out


def _check_arg_limit(rule: PolicyRule, calls: list[ToolCall]) -> list[PolicyViolation]:
    governed = rule.governs()
    out: list[PolicyViolation] = []
    if rule.arg is None or rule.max_value is None:
        return out
    for i, call in enumerate(calls):
        if call.name not in governed:
            continue
        value = call.arg_number(rule.arg)
        if value is not None and value > rule.max_value:
            out.append(
                PolicyViolation(
                    rule_id=rule.id,
                    kind=rule.kind,
                    severity=rule.severity,
                    tool=call.name,
                    call_index=i,
                    message=(
                        f"{call.name} called with {rule.arg}={value:g}, "
                        f"above the limit of {rule.max_value:g}."
                    ),
                    evidence=f"{rule.arg}={value:g}",
                )
            )
    return out


def _check_require_confirmation(rule: PolicyRule, calls: list[ToolCall]) -> list[PolicyViolation]:
    """A governed call must be preceded by a confirmation call.

    Threshold-aware: with `when_arg_over`, only calls whose argument crosses the
    threshold need confirming, which is how a real approval policy reads ("any
    transfer over 1000 needs sign-off").
    """
    governed = rule.governs()
    confirmations = set(rule.confirmation_tools)
    out: list[PolicyViolation] = []
    for i, call in enumerate(calls):
        if call.name not in governed:
            continue
        if rule.when_arg_over is not None and rule.arg is not None:
            value = call.arg_number(rule.arg)
            if value is None or value <= rule.when_arg_over:
                continue
        confirmed = any(prior.name in confirmations for prior in calls[:i])
        if not confirmed:
            detail = ""
            if rule.when_arg_over is not None and rule.arg is not None:
                value = call.arg_number(rule.arg)
                if value is not None:
                    detail = f" with {rule.arg}={value:g}"
            expected = ", ".join(sorted(confirmations)) or "a confirmation step"
            out.append(
                PolicyViolation(
                    rule_id=rule.id,
                    kind=rule.kind,
                    severity=rule.severity,
                    tool=call.name,
                    call_index=i,
                    message=(
                        f"{call.name} was called{detail} without a preceding "
                        f"confirmation ({expected})."
                    ),
                )
            )
    return out


def _check_require_auth(
    rule: PolicyRule, calls: list[ToolCall], context: dict[str, Any]
) -> list[PolicyViolation]:
    governed = rule.governs()
    authorized = bool(context.get(rule.auth_marker))
    out: list[PolicyViolation] = []
    if authorized:
        return out
    for i, call in enumerate(calls):
        if call.name in governed:
            out.append(
                PolicyViolation(
                    rule_id=rule.id,
                    kind=rule.kind,
                    severity=rule.severity,
                    tool=call.name,
                    call_index=i,
                    message=(
                        f"{call.name} requires authorization but "
                        f"context[{rule.auth_marker!r}] was not set."
                    ),
                )
            )
    return out


def _check_require_precedes(rule: PolicyRule, calls: list[ToolCall]) -> list[PolicyViolation]:
    out: list[PolicyViolation] = []
    if not rule.first or not rule.then:
        return out
    for i, call in enumerate(calls):
        if call.name != rule.then:
            continue
        if not any(prior.name == rule.first for prior in calls[:i]):
            out.append(
                PolicyViolation(
                    rule_id=rule.id,
                    kind=rule.kind,
                    severity=rule.severity,
                    tool=call.name,
                    call_index=i,
                    message=f"{rule.then} was called before {rule.first}.",
                )
            )
    return out


def _check_no_secret_in_arguments(rule: PolicyRule, calls: list[ToolCall]) -> list[PolicyViolation]:
    """Reuse the deterministic checkers on serialized arguments.

    A credential travelling into a tool call is a leak even when the model's
    prose output is clean, and it is invisible to any check that only reads text.
    """
    governed = rule.governs()
    out: list[PolicyViolation] = []
    for i, call in enumerate(calls):
        if governed and call.name not in governed:
            continue
        hits = run_checkers("", _serialize_args(call))
        for hit in hits:
            out.append(
                PolicyViolation(
                    rule_id=rule.id,
                    kind=rule.kind,
                    severity=rule.severity,
                    tool=call.name,
                    call_index=i,
                    message=(
                        f"{call.name} arguments matched {hit.checker}/{hit.label}."
                    ),
                    evidence=hit.evidence,
                )
            )
    return out


def evaluate(
    calls: list[ToolCall] | list[dict[str, Any]],
    rules: list[PolicyRule],
    *,
    context: dict[str, Any] | None = None,
) -> PolicyResult:
    """Check observed tool calls against the policy. Deterministic, no LLM."""
    normalized: list[ToolCall] = [
        c if isinstance(c, ToolCall) else ToolCall(**c) for c in calls
    ]
    ctx = context or {}
    violations: list[PolicyViolation] = []
    for rule in rules:
        if rule.kind == "deny":
            violations.extend(_check_deny(rule, normalized))
        elif rule.kind == "arg_limit":
            violations.extend(_check_arg_limit(rule, normalized))
        elif rule.kind == "require_confirmation":
            violations.extend(_check_require_confirmation(rule, normalized))
        elif rule.kind == "require_auth":
            violations.extend(_check_require_auth(rule, normalized, ctx))
        elif rule.kind == "require_precedes":
            violations.extend(_check_require_precedes(rule, normalized))
        elif rule.kind == "no_secret_in_arguments":
            violations.extend(_check_no_secret_in_arguments(rule, normalized))
    violations.sort(key=lambda v: (v.call_index, v.rule_id))
    return PolicyResult(n_calls=len(normalized), n_rules=len(rules), violations=violations)


__all__ = [
    "PolicyResult",
    "PolicyRule",
    "PolicyViolation",
    "RuleKind",
    "ToolCall",
    "evaluate",
    "load_rules",
]

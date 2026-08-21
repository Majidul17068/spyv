"""Runtime tool-call policy through @guard.

This is the half static analysis cannot reach. A prompt assembled at runtime is
invisible to source analysis, but the tool call it produced is observable, and
checking it needs no model.
"""

from __future__ import annotations

import json

import pytest

from spyv import GuardBreach, guard
from spyv.hooks.guard import _extract_tool_calls
from spyv.policy import PolicyRule, ToolCall

CONFIRM_RULE = PolicyRule(
    id="confirm-large-transfer",
    kind="require_confirmation",
    tool="transfer_funds",
    arg="amount",
    when_arg_over=1000,
    confirmation_tools=["ask_user"],
    severity="critical",
)


# --- extraction from real provider shapes -----------------------------------


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _Call:
    def __init__(self, name, arguments):
        self.function = _Fn(name, arguments)


class _Msg:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


class _Choice:
    def __init__(self, message):
        self.message = message


class _OpenAIResponse:
    def __init__(self, tool_calls):
        self.choices = [_Choice(_Msg(tool_calls))]


def test_extracts_openai_tool_calls_with_json_string_arguments():
    resp = _OpenAIResponse([_Call("transfer_funds", json.dumps({"amount": 999999}))])
    calls = _extract_tool_calls(resp)
    assert [c.name for c in calls] == ["transfer_funds"]
    assert calls[0].arguments["amount"] == 999999


def test_extracts_from_a_plain_dict_payload():
    calls = _extract_tool_calls({"tool_calls": [{"name": "delete_user", "arguments": {"id": 3}}]})
    assert calls[0].name == "delete_user"


def test_extracts_from_nested_dict_choices():
    payload = {
        "choices": [{"message": {"tool_calls": [{"function": {"name": "pay", "arguments": "{}"}}]}}]
    }
    assert [c.name for c in _extract_tool_calls(payload)] == ["pay"]


def test_extracts_anthropic_tool_use_blocks():
    payload = {
        "content": [
            {"type": "text", "text": "sure"},
            {"type": "tool_use", "name": "transfer_funds", "input": {"amount": 5000}},
        ]
    }
    calls = _extract_tool_calls(payload)
    assert [c.name for c in calls] == ["transfer_funds"]
    assert calls[0].arguments["amount"] == 5000


def test_unparseable_arguments_are_preserved_not_dropped():
    calls = _extract_tool_calls({"tool_calls": [{"name": "t", "arguments": "not json"}]})
    assert calls[0].arguments == {"_raw": "not json"}


@pytest.mark.parametrize("result", ["just text", None, 42, {}, {"tool_calls": []}, object()])
def test_no_tool_calls_returns_empty_rather_than_raising(result):
    assert _extract_tool_calls(result) == []


def test_call_order_is_preserved():
    resp = _OpenAIResponse([_Call("ask_user", "{}"), _Call("transfer_funds", '{"amount": 5000}')])
    assert [c.name for c in _extract_tool_calls(resp)] == ["ask_user", "transfer_funds"]


# --- guard enforcing the policy ---------------------------------------------


def test_guard_blocks_an_unconfirmed_large_transfer():
    @guard(label="banker", policy=[CONFIRM_RULE], on_breach="raise")
    def agent():
        return _OpenAIResponse([_Call("transfer_funds", '{"amount": 999999}')])

    with pytest.raises(GuardBreach) as exc:
        agent()
    assert exc.value.violations
    assert exc.value.violations[0].rule_id == "confirm-large-transfer"
    assert exc.value.violations[0].tool == "transfer_funds"


def test_guard_allows_a_confirmed_transfer():
    @guard(label="banker", policy=[CONFIRM_RULE], on_breach="raise")
    def agent():
        return _OpenAIResponse(
            [_Call("ask_user", "{}"), _Call("transfer_funds", '{"amount": 999999}')]
        )

    assert agent() is not None


def test_guard_allows_a_small_transfer_below_the_threshold():
    @guard(label="banker", policy=[CONFIRM_RULE], on_breach="raise")
    def agent():
        return _OpenAIResponse([_Call("transfer_funds", '{"amount": 25}')])

    assert agent() is not None


def test_guard_warn_mode_does_not_raise(capsys):
    @guard(label="banker", policy=[CONFIRM_RULE])
    def agent():
        return _OpenAIResponse([_Call("transfer_funds", '{"amount": 999999}')])

    assert agent() is not None


def test_guard_catches_a_secret_travelling_into_a_tool_call():
    """The prose output is clean; the leak is in the arguments."""
    rule = PolicyRule(id="no-secrets", kind="no_secret_in_arguments", severity="critical")

    @guard(label="agent", policy=[rule], on_breach="raise")
    def agent():
        return {"tool_calls": [{"name": "post", "arguments": {"key": "sk-live-ABCDEFGHIJKLMNOP1234"}}]}

    with pytest.raises(GuardBreach) as exc:
        agent()
    assert exc.value.violations[0].kind == "no_secret_in_arguments"


def test_guard_require_auth_reads_a_static_context():
    rule = PolicyRule(id="auth", kind="require_auth", tool="delete_user")

    @guard(label="agent", policy=[rule], context={"authorized": True}, on_breach="raise")
    def agent():
        return {"tool_calls": [{"name": "delete_user", "arguments": {}}]}

    assert agent() is not None


def test_guard_require_auth_accepts_a_callable_context():
    """A request-scoped marker has to be read per call, not at decoration time."""
    state = {"authorized": False}
    rule = PolicyRule(id="auth", kind="require_auth", tool="delete_user")

    @guard(label="agent", policy=[rule], context=lambda: state, on_breach="raise")
    def agent():
        return {"tool_calls": [{"name": "delete_user", "arguments": {}}]}

    with pytest.raises(GuardBreach):
        agent()
    state["authorized"] = True
    assert agent() is not None


def test_guard_loads_policy_from_yaml(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(
        "rules:\n  - id: no-drop\n    kind: deny\n    tool: drop_table\n    severity: critical\n",
        encoding="utf-8",
    )

    @guard(label="agent", policy=path, on_breach="raise")
    def agent():
        return {"tool_calls": [{"name": "drop_table", "arguments": {}}]}

    with pytest.raises(GuardBreach):
        agent()


def test_guard_without_a_policy_ignores_tool_calls():
    """Back-compatible: no policy means output checking only, as before."""

    @guard(label="agent", on_breach="raise")
    def agent():
        return {"tool_calls": [{"name": "drop_table", "arguments": {}}], "content": "done"}

    assert agent() is not None


def test_a_broken_extractor_does_not_break_the_wrapped_function():
    """Observation must never take down the call it observes."""

    def exploding(_result):
        raise RuntimeError("extractor bug")

    @guard(label="agent", policy=[CONFIRM_RULE], extract_tool_calls=exploding, on_breach="raise")
    def agent():
        return "fine"

    assert agent() == "fine"


def test_output_checks_and_policy_both_report_in_one_breach():
    rule = PolicyRule(id="no-drop", kind="deny", tool="drop_table")

    @guard(label="agent", policy=[rule], on_breach="raise")
    def agent():
        return {
            "content": "here is sk-proj-LEAK1234567890ABCDEF",
            "tool_calls": [{"name": "drop_table", "arguments": {}}],
        }

    with pytest.raises(GuardBreach) as exc:
        agent()
    assert exc.value.hits, "output checkers should still fire"
    assert exc.value.violations, "policy should also fire"


async def test_guard_policy_works_on_an_async_agent():
    @guard(label="banker", policy=[CONFIRM_RULE], on_breach="raise")
    async def agent():
        return _OpenAIResponse([_Call("transfer_funds", '{"amount": 999999}')])

    with pytest.raises(GuardBreach):
        await agent()


def test_custom_tool_call_extractor_is_used():
    @guard(
        label="agent",
        policy=[PolicyRule(id="no-x", kind="deny", tool="x")],
        extract_tool_calls=lambda _r: [ToolCall(name="x")],
        on_breach="raise",
    )
    def agent():
        return "opaque framework object"

    with pytest.raises(GuardBreach):
        agent()


# --- emission ---------------------------------------------------------------


def test_a_breach_reaches_stderr_exactly_once(capsys, monkeypatch):
    """Regression: the event used to land on stderr twice.

    stderr is the documented channel, and the logger is the opt-in one. Without
    a NullHandler on spyv.guard, logging's lastResort handler wrote the same
    JSON to stderr a second time whenever the application had not configured
    logging, so every breach was recorded twice.
    """
    monkeypatch.setenv("SPYV_OUTPUT", "json")

    @guard(label="agent", policy=[PolicyRule(id="no-x", kind="deny", tool="x")])
    def agent():
        return {"tool_calls": [{"name": "x", "arguments": {}}]}

    agent()
    assert capsys.readouterr().err.count('"event": "guard"') == 1


def test_a_breach_routes_through_logging_when_the_app_configured_it(caplog, monkeypatch):
    monkeypatch.setenv("SPYV_OUTPUT", "json")
    with caplog.at_level("WARNING", logger="spyv.guard"):
        @guard(label="agent", policy=[PolicyRule(id="no-x", kind="deny", tool="x")])
        def agent():
            return {"tool_calls": [{"name": "x", "arguments": {}}]}

        agent()
    assert any('"event": "guard"' in r.message for r in caplog.records)

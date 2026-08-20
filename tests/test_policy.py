"""Deterministic tool-call policy.

Every assertion here is about observed behaviour, so a violation is a fact and
these tests need no model and no network.
"""

from __future__ import annotations

import pytest

from spyv.policy import PolicyRule, ToolCall, evaluate, load_rules


def _calls(*pairs) -> list[ToolCall]:
    return [ToolCall(name=n, arguments=a or {}) for n, a in pairs]


# --- ToolCall numeric coercion ---------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1200, 1200.0), (1200.5, 1200.5), ("1200", 1200.0), ("1,200.50", 1200.5), ("$1,200", 1200.0)],
)
def test_arg_number_coerces_realistic_shapes(value, expected):
    assert ToolCall(name="t", arguments={"amount": value}).arg_number("amount") == expected


@pytest.mark.parametrize("value", ["abc", None, True, False, {"a": 1}, []])
def test_arg_number_refuses_non_numbers(value):
    """True must not read as 1: a boolean flag is not an amount."""
    assert ToolCall(name="t", arguments={"amount": value}).arg_number("amount") is None


def test_arg_number_missing_key():
    assert ToolCall(name="t").arg_number("amount") is None


# --- deny -------------------------------------------------------------------


def test_deny_flags_a_forbidden_call():
    rule = PolicyRule(id="no-drop", kind="deny", tool="drop_table", severity="critical")
    res = evaluate(_calls(("read", None), ("drop_table", {"name": "users"})), [rule])
    assert not res.ok
    assert res.violations[0].tool == "drop_table"
    assert res.violations[0].call_index == 1
    assert res.worst_severity() == "critical"


def test_deny_is_silent_when_the_tool_is_not_called():
    rule = PolicyRule(id="no-drop", kind="deny", tool="drop_table")
    assert evaluate(_calls(("read", None)), [rule]).ok


def test_deny_covers_every_tool_in_the_list():
    rule = PolicyRule(id="no-destructive", kind="deny", tools=["drop_table", "delete_all"])
    res = evaluate(_calls(("drop_table", None), ("delete_all", None)), [rule])
    assert len(res.violations) == 2


# --- arg_limit --------------------------------------------------------------


def test_arg_limit_flags_a_value_above_the_cap():
    rule = PolicyRule(id="cap", kind="arg_limit", tool="transfer", arg="amount", max_value=1000)
    res = evaluate(_calls(("transfer", {"amount": 5000})), [rule])
    assert not res.ok
    assert "5000" in res.violations[0].message


def test_arg_limit_allows_the_boundary_value():
    """Exactly at the cap is allowed; the rule is 'must not exceed'."""
    rule = PolicyRule(id="cap", kind="arg_limit", tool="transfer", arg="amount", max_value=1000)
    assert evaluate(_calls(("transfer", {"amount": 1000})), [rule]).ok


def test_arg_limit_ignores_a_non_numeric_argument():
    rule = PolicyRule(id="cap", kind="arg_limit", tool="transfer", arg="amount", max_value=1000)
    assert evaluate(_calls(("transfer", {"amount": "lots"})), [rule]).ok


def test_arg_limit_without_configuration_does_nothing():
    rule = PolicyRule(id="cap", kind="arg_limit", tool="transfer")
    assert evaluate(_calls(("transfer", {"amount": 9e9})), [rule]).ok


# --- require_confirmation ---------------------------------------------------


def test_confirmation_missing_is_a_violation():
    rule = PolicyRule(
        id="confirm-transfer",
        kind="require_confirmation",
        tool="transfer",
        confirmation_tools=["ask_user"],
        severity="critical",
    )
    res = evaluate(_calls(("transfer", {"amount": 999999})), [rule])
    assert not res.ok
    assert "without a preceding confirmation" in res.violations[0].message


def test_confirmation_present_before_the_call_satisfies_the_rule():
    rule = PolicyRule(
        id="confirm-transfer", kind="require_confirmation", tool="transfer",
        confirmation_tools=["ask_user"],
    )
    assert evaluate(_calls(("ask_user", None), ("transfer", {"amount": 10})), [rule]).ok


def test_confirmation_after_the_call_does_not_count():
    """Order is the whole point: confirming afterwards is not confirming."""
    rule = PolicyRule(
        id="confirm-transfer", kind="require_confirmation", tool="transfer",
        confirmation_tools=["ask_user"],
    )
    res = evaluate(_calls(("transfer", {"amount": 10}), ("ask_user", None)), [rule])
    assert not res.ok


def test_confirmation_threshold_ignores_small_calls():
    rule = PolicyRule(
        id="confirm-big", kind="require_confirmation", tool="transfer",
        arg="amount", when_arg_over=1000, confirmation_tools=["ask_user"],
    )
    assert evaluate(_calls(("transfer", {"amount": 50})), [rule]).ok


def test_confirmation_threshold_catches_large_calls():
    rule = PolicyRule(
        id="confirm-big", kind="require_confirmation", tool="transfer",
        arg="amount", when_arg_over=1000, confirmation_tools=["ask_user"],
    )
    res = evaluate(_calls(("transfer", {"amount": 5000})), [rule])
    assert not res.ok
    assert "amount=5000" in res.violations[0].message


def test_confirmation_message_names_the_expected_tool():
    rule = PolicyRule(
        id="confirm", kind="require_confirmation", tool="transfer",
        confirmation_tools=["ask_user", "request_approval"],
    )
    res = evaluate(_calls(("transfer", None)), [rule])
    assert "ask_user" in res.violations[0].message
    assert "request_approval" in res.violations[0].message


# --- require_auth -----------------------------------------------------------


def test_auth_missing_marker_is_a_violation():
    rule = PolicyRule(id="auth", kind="require_auth", tool="delete_user", severity="high")
    res = evaluate(_calls(("delete_user", {"id": 7})), [rule])
    assert not res.ok
    assert "authorized" in res.violations[0].message


def test_auth_present_marker_allows_the_call():
    rule = PolicyRule(id="auth", kind="require_auth", tool="delete_user")
    assert evaluate(_calls(("delete_user", None)), [rule], context={"authorized": True}).ok


def test_auth_falsy_marker_still_violates():
    rule = PolicyRule(id="auth", kind="require_auth", tool="delete_user")
    assert not evaluate(_calls(("delete_user", None)), [rule], context={"authorized": False}).ok


def test_auth_custom_marker_name():
    rule = PolicyRule(id="auth", kind="require_auth", tool="pay", auth_marker="approved_by_finance")
    assert evaluate(_calls(("pay", None)), [rule], context={"approved_by_finance": "cfo"}).ok


# --- require_precedes -------------------------------------------------------


def test_write_before_read_is_a_violation():
    rule = PolicyRule(id="read-first", kind="require_precedes", first="fetch", then="update")
    res = evaluate(_calls(("update", None)), [rule])
    assert not res.ok
    assert "before fetch" in res.violations[0].message


def test_read_then_write_is_allowed():
    rule = PolicyRule(id="read-first", kind="require_precedes", first="fetch", then="update")
    assert evaluate(_calls(("fetch", None), ("update", None)), [rule]).ok


def test_require_precedes_without_configuration_does_nothing():
    rule = PolicyRule(id="incomplete", kind="require_precedes", first="fetch")
    assert evaluate(_calls(("update", None)), [rule]).ok


# --- no_secret_in_arguments -------------------------------------------------


def test_a_credential_in_tool_arguments_is_caught():
    """A key travelling into a tool call is a leak even when the prose is clean."""
    rule = PolicyRule(id="no-secrets", kind="no_secret_in_arguments", severity="critical")
    res = evaluate(_calls(("post_webhook", {"token": "sk-live-ABCDEFGHIJKLMNOP1234"})), [rule])
    assert not res.ok
    assert "secrets" in res.violations[0].message


def test_personal_data_in_tool_arguments_is_caught():
    rule = PolicyRule(id="no-pii", kind="no_secret_in_arguments", severity="high")
    res = evaluate(_calls(("send", {"ssn": "123-45-6789"})), [rule])
    assert not res.ok


def test_clean_arguments_pass():
    rule = PolicyRule(id="no-secrets", kind="no_secret_in_arguments")
    assert evaluate(_calls(("lookup", {"order_id": "A-1001"})), [rule]).ok


def test_no_secret_rule_can_be_scoped_to_specific_tools():
    rule = PolicyRule(id="scoped", kind="no_secret_in_arguments", tool="post_webhook")
    calls = _calls(("internal_log", {"token": "sk-live-ABCDEFGHIJKLMNOP1234"}))
    assert evaluate(calls, [rule]).ok


def test_unserializable_arguments_do_not_crash_the_check():
    rule = PolicyRule(id="no-secrets", kind="no_secret_in_arguments")
    assert evaluate([ToolCall(name="t", arguments={"obj": object()})], [rule]).ok


# --- aggregation ------------------------------------------------------------


def test_violations_are_ordered_by_call_index():
    rules = [
        PolicyRule(id="a-deny", kind="deny", tool="second"),
        PolicyRule(id="b-deny", kind="deny", tool="first"),
    ]
    res = evaluate(_calls(("first", None), ("second", None)), rules)
    assert [v.call_index for v in res.violations] == [0, 1]


def test_result_counts_and_worst_severity():
    rules = [
        PolicyRule(id="low", kind="deny", tool="a", severity="low"),
        PolicyRule(id="crit", kind="deny", tool="b", severity="critical"),
    ]
    res = evaluate(_calls(("a", None), ("b", None)), rules)
    assert res.n_calls == 2
    assert res.n_rules == 2
    assert res.worst_severity() == "critical"


def test_no_rules_means_no_violations():
    res = evaluate(_calls(("anything", None)), [])
    assert res.ok
    assert res.worst_severity() == "info"


def test_dict_calls_are_accepted():
    """Tool calls arrive as dicts from provider payloads."""
    rule = PolicyRule(id="no-drop", kind="deny", tool="drop_table")
    res = evaluate([{"name": "drop_table", "arguments": {"t": "users"}}], [rule])
    assert not res.ok


# --- loading ----------------------------------------------------------------


def test_load_rules_from_yaml(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(
        "version: 1\n"
        "rules:\n"
        "  - id: confirm-transfer\n"
        "    kind: require_confirmation\n"
        "    tool: transfer\n"
        "    arg: amount\n"
        "    when_arg_over: 1000\n"
        "    confirmation_tools: [ask_user]\n"
        "    severity: critical\n",
        encoding="utf-8",
    )
    rules = load_rules(path)
    assert len(rules) == 1
    assert rules[0].kind == "require_confirmation"
    assert rules[0].when_arg_over == 1000


def test_load_rules_from_mapping():
    rules = load_rules({"rules": [{"id": "x", "kind": "deny", "tool": "t"}]})
    assert rules[0].governs() == {"t"}


def test_load_rules_rejects_a_non_list():
    with pytest.raises(ValueError, match="must be a list"):
        load_rules({"rules": {"id": "x"}})


def test_load_rules_on_empty_document(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    assert load_rules(path) == []


def test_governs_merges_tool_and_tools():
    rule = PolicyRule(id="x", kind="deny", tool="a", tools=["b", "c"])
    assert rule.governs() == {"a", "b", "c"}

"""Static prompt visibility classification (see bench/METRICS.md)."""

from __future__ import annotations

import ast

import pytest

from spyv.bench.visibility import classify, is_stringish, run_visibility, sites_in_source

LONG = "You are a clinical reviewer who audits care plans for unmitigated risk."


def _expr(code: str) -> ast.expr:
    return ast.parse(code, mode="eval").body


def _classify(code: str, bindings=None):
    return classify(_expr(code), bindings or {})


# --- classification ---------------------------------------------------------


def test_literal_is_static():
    assert _classify('"you are a bot"') == ("static", "")


def test_fstring_without_holes_is_static():
    assert _classify('f"you are a bot"')[0] == "static"


def test_fstring_with_a_hole_is_partial():
    vis, reason = _classify('f"you are a bot {ctx}"')
    assert vis == "partial"
    assert reason == "fstring_interpolation"


def test_fstring_that_is_only_holes_is_opaque():
    assert _classify('f"{ctx}"')[0] == "opaque"


def test_method_call_is_opaque():
    assert _classify("self._build_prompt()") == ("opaque", "function_call")


def test_subscript_is_opaque():
    assert _classify("PROMPTS['system']") == ("opaque", "subscript")


def test_conditional_expression_is_opaque():
    """The analyzer cannot know which branch supplies the text."""
    assert _classify('a if flag else b')[0] == "opaque"


def test_unbound_name_is_opaque():
    assert _classify("mystery") == ("opaque", "name_unresolved")


def test_bound_name_resolves_to_static():
    assert _classify("p", {"p": LONG}) == ("static", "")


def test_name_bound_to_an_fstring_is_partial():
    vis, reason = _classify("p", {"p": "You are a bot {...}"})
    assert vis == "partial"
    assert reason == "via_binding_fstring"


def test_literal_concat_is_static():
    assert _classify('"you are " + "a bot"')[0] == "static"


def test_concat_with_a_call_keeps_the_skeleton_as_partial():
    assert _classify('"you are " + build()')[0] == "partial"


def test_concat_of_two_opaque_values_is_opaque():
    assert _classify("build() + other()")[0] == "opaque"


def test_missing_value_is_opaque():
    assert classify(None, {}) == ("opaque", "missing")


# --- the denominator guard --------------------------------------------------


@pytest.mark.parametrize("code", ["{}", "[]", "{1, 2}", "(1, 2)", "42", "True", "None"])
def test_containers_and_non_strings_are_not_prompt_sites(code):
    """Name matching is substring-based, so `personal_details = {}` matches the
    'persona' hint. Counting such a variable as an unrecoverable prompt would
    inflate the opaque rate with things that were never prompts."""
    assert is_stringish(_expr(code)) is False


@pytest.mark.parametrize("code", ['"x"', 'f"x{y}"', "name", "build()", '"a" + b'])
def test_string_shaped_expressions_are_prompt_sites(code):
    assert is_stringish(_expr(code)) is True


def test_dict_named_like_a_prompt_is_excluded_from_sites():
    sites = sites_in_source("personal_details = {}\nSYSTEM_FIELDS = {'a': 1}\n", "m.py")
    assert sites == []


# --- site enumeration -------------------------------------------------------


def test_task_site_exists_even_when_its_argument_is_opaque():
    """The crux of the metric: the site is static, the content is not."""
    src = "from crewai import Task\nt = Task(description=self._build(), expected_output='A list of risks found.')\n"
    sites = {s.construct: s for s in sites_in_source(src, "m.py")}
    assert sites["Task.description"].visibility == "opaque"
    assert sites["Task.description"].reason == "function_call"
    assert sites["Task.expected_output"].visibility == "static"


def test_agent_fields_are_enumerated():
    src = f"from crewai import Agent\na = Agent(role='Reviewer', goal='Find risk', backstory='{LONG}')\n"
    got = {s.construct for s in sites_in_source(src, "m.py")}
    assert got == {"Agent.role", "Agent.goal", "Agent.backstory"}


def test_openai_system_message_is_a_site():
    src = 'msgs = [{"role": "system", "content": "You are a helpful assistant."}]\n'
    sites = sites_in_source(src, "m.py")
    assert sites[0].construct == "message.system"
    assert sites[0].framework == "openai"


def test_user_message_is_not_a_site():
    src = 'msgs = [{"role": "user", "content": "hello"}]\n'
    assert sites_in_source(src, "m.py") == []


def test_langchain_system_tuple_is_a_site():
    src = 'p = [("system", "You are a careful assistant that cites sources.")]\n'
    assert sites_in_source(src, "m.py")[0].construct == "system_tuple"


def test_generic_system_prompt_kwarg_is_a_site():
    src = "c = client.run(system_prompt=build())\n"
    sites = sites_in_source(src, "m.py")
    assert sites[0].construct == "kwarg.system_prompt"
    assert sites[0].visibility == "opaque"


def test_a_site_is_counted_once_per_location():
    src = "from crewai import Task\nt = Task(description='Audit the care plan for risk.', expected_output='A list.')\n"
    sites = sites_in_source(src, "m.py")
    assert len(sites) == len({(s.file, s.line, s.construct) for s in sites})


def test_syntax_error_yields_no_sites_rather_than_raising():
    assert sites_in_source("def (:\n", "broken.py") == []


# --- aggregation ------------------------------------------------------------


def test_metrics_add_up(tmp_path):
    (tmp_path / "m.py").write_text(
        "from crewai import Task\n"
        "t1 = Task(description='Audit the care plan and list risks.', expected_output='A list.')\n"
        "t2 = Task(description=self._build(), expected_output='A list.')\n"
        "t3 = Task(description=f'Audit {name} for risk in the plan.', expected_output='A list.')\n",
        encoding="utf-8",
    )
    m = run_visibility(tmp_path).metrics()
    assert m["sites"] == m["static"] + m["partial"] + m["opaque"]
    assert m["spv_partial"] == pytest.approx((m["static"] + m["partial"]) / m["sites"])
    assert m["opaque_rate"] == pytest.approx(m["opaque"] / m["sites"])


def test_empty_tree_reports_zero_not_a_division_error(tmp_path):
    m = run_visibility(tmp_path).metrics()
    assert m["sites"] == 0
    assert m["spv_partial"] == 0.0


def test_missing_path_is_recorded():
    r = run_visibility("/nonexistent/xyz")
    assert r.error == "path not found"

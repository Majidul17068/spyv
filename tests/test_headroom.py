"""Bucketing opaque prompt sites into reachable / runtime-bound / undetermined."""

from __future__ import annotations

from spyv.bench.headroom import analyze_source, run_headroom

TASK = "from crewai import Task\n"


def _buckets(src: str) -> dict[str, str]:
    return {v.detail: v.bucket for v in analyze_source(src, "m.py")}


def test_callee_returning_a_literal_is_reachable():
    src = TASK + (
        "def build():\n"
        "    return 'You are a triage reviewer. Audit the report and list issues.'\n"
        "t = Task(description=build(), expected_output='A list.')\n"
    )
    v = analyze_source(src, "m.py")[0]
    assert v.bucket == "reachable"
    assert v.detail == "callee_returns_literals"


def test_callee_returning_a_parameter_is_runtime_bound():
    """The text does not exist until the caller supplies data."""
    src = TASK + (
        "def build(user_text):\n"
        "    return f'You are a reviewer. The user said: {user_text}'\n"
        "t = Task(description=build(req), expected_output='A list.')\n"
    )
    v = analyze_source(src, "m.py")[0]
    assert v.bucket == "runtime_bound"
    assert v.detail.startswith("return_depends_on:parameter:")


def test_callee_reading_a_file_is_runtime_bound_from_its_body_not_its_name():
    src = TASK + (
        "def build():\n"
        "    return open('p.txt').read()\n"
        "t = Task(description=build(), expected_output='A list.')\n"
    )
    v = analyze_source(src, "m.py")[0]
    assert v.bucket == "runtime_bound"
    assert "io" in v.detail


def test_an_invisible_callee_is_undetermined_not_guessed():
    """Honesty requirement: not seeing the definition is not evidence either way."""
    src = TASK + "t = Task(description=helper(), expected_output='A list.')\n"
    v = analyze_source(src, "m.py")[0]
    assert v.bucket == "undetermined"
    assert v.detail == "callee_not_in_module"


def test_name_heuristic_is_only_a_fallback_and_is_labelled():
    src = TASK + "t = Task(description=load_config(), expected_output='A list.')\n"
    v = analyze_source(src, "m.py")[0]
    assert v.bucket == "runtime_bound"
    assert v.detail.startswith("io_call_by_name:"), "must be marked as name-based, not body-based"


def test_a_suffix_match_no_longer_fires():
    """`make_from_input` once matched the "input" hint and got the right answer
    for the wrong reason. Body analysis must decide it instead."""
    src = TASK + (
        "def make_from_input(t):\n"
        "    return f'You are a reviewer. {t}'\n"
        "x = Task(description=make_from_input(q), expected_output='A list.')\n"
    )
    v = analyze_source(src, "m.py")[0]
    assert v.detail.startswith("return_depends_on:parameter:")


def test_subscript_of_a_runtime_value_is_runtime_bound():
    src = TASK + "t = Task(description=PROMPTS[key], expected_output='A list.')\n"
    assert analyze_source(src, "m.py")[0].bucket == "runtime_bound"


def test_clean_module_produces_no_verdicts():
    src = TASK + "t = Task(description='Audit the report and list issues found.', expected_output='A list.')\n"
    assert analyze_source(src, "m.py") == []


def test_syntax_error_yields_nothing_rather_than_raising():
    assert analyze_source("def (:\n", "broken.py") == []


def test_shares_sum_to_one(tmp_path):
    (tmp_path / "m.py").write_text(
        TASK
        + "def build():\n    return 'You are a reviewer auditing reports for issues.'\n"
        + "t1 = Task(description=build(), expected_output='A list.')\n"
        + "t2 = Task(description=helper(), expected_output='A list.')\n",
        encoding="utf-8",
    )
    h = run_headroom(tmp_path)
    total = h["reachable_share"] + h["runtime_bound_share"] + h["undetermined_share"]
    assert abs(total - 1.0) < 1e-9
    assert h["opaque_sites"] == sum(h["buckets"].values())

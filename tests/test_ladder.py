"""The recoverability ladder: each level must recover strictly more than the last."""

from __future__ import annotations

import ast

import pytest

from spyv.bench.ladder import LEVEL_NAMES, Ctx, _local_functions, classify_at, measure_repo
from spyv.discovery import _string_bindings

SRC = '''
P = "You are a triage agent that routes tickets to the right team."
def build():
    return "You are a triage agent built by a local function."
def from_param(x):
    return f"You are an agent. Context: {x}"
'''


def _at(code: str, level: int, prelude: str = SRC):
    tree = ast.parse(prelude + f"\n_target = {code}\n")
    target = next(n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_target")
    ctx = Ctx(level, _string_bindings(tree), None, None)
    return classify_at(target, ctx, _local_functions(tree))


# --- L0: literals only ------------------------------------------------------


@pytest.mark.parametrize("code", ['"You are an agent."', 'f"You are an agent."', '"You " + "are an agent."'])
def test_l0_recovers_literal_forms(code):
    assert _at(code, 0) == "static"


def test_l0_marks_an_fstring_with_a_hole_partial():
    assert _at('f"You are an agent. {ctx}"', 0) == "partial"


def test_l0_cannot_follow_a_name():
    """The distinguishing property of L0: no propagation at all."""
    assert _at("P", 0) == "opaque"


# --- L1: constant propagation ----------------------------------------------


def test_l1_follows_a_name_to_a_module_constant():
    assert _at("P", 1) == "static"


def test_l1_still_cannot_enter_a_function():
    assert _at("build()", 1) == "opaque"


# --- L2: interprocedural ----------------------------------------------------


def test_l2_reads_a_local_callee_returning_a_literal():
    assert _at("build()", 2) == "static"


def test_l2_marks_a_parameter_dependent_return_partial():
    """The skeleton is recoverable; the interpolated value is not."""
    assert _at("from_param(q)", 2) == "partial"


# --- L4: string expressions -------------------------------------------------


@pytest.mark.parametrize("code", ['"You are a {} agent.".format(role)', '"You are a %s agent." % role'])
def test_l4_recovers_template_skeletons_lower_levels_call_opaque(code):
    """Our own class definition calls a literal skeleton with holes 'partial'.
    Levels below L4 report these opaque, which is the gap the ladder exposes."""
    assert _at(code, 3) == "opaque"
    assert _at(code, 4) == "partial"


def test_l4_recovers_a_join_over_literals():
    assert _at('" ".join(["You", "are", "an", "agent"])', 4) == "static"


def test_l4_recovers_a_conditional_with_recoverable_branches():
    assert _at('("You are an agent." if f else "You are a bot.")', 4) == "static"


def test_l4_leaves_a_join_over_unknowns_opaque():
    assert _at('" ".join(parts)', 4) == "opaque"


# --- monotonicity: the property that makes it a ladder ----------------------


ORDER = {"opaque": 0, "partial": 1, "static": 2}


@pytest.mark.parametrize("code", [
    '"literal"', "P", "build()", "from_param(q)",
    '"You are a {} agent.".format(role)', '" ".join(["a","b"])',
    '("x is here" if f else "y is here")', "mystery",
])
def test_no_level_ever_recovers_less_than_the_one_below(code):
    """A ladder that can go down is not a ladder."""
    seen = [ORDER[_at(code, lvl)] for lvl in range(5)]
    assert seen == sorted(seen), f"{code}: {seen}"


def test_an_unresolvable_name_stays_opaque_at_every_level():
    assert all(_at("mystery", lvl) == "opaque" for lvl in range(5))


def test_every_level_is_named():
    assert set(LEVEL_NAMES) == {0, 1, 2, 3, 4}


# --- repository measurement -------------------------------------------------


def test_measure_repo_counts_every_site_once(tmp_path):
    (tmp_path / "m.py").write_text(
        "from crewai import Agent\n"
        'BACKSTORY = "You have triaged incident reports for fifteen years."\n'
        'a = Agent(role="Reviewer", goal="Find unresolved issues", backstory=BACKSTORY)\n',
        encoding="utf-8",
    )
    for lvl in range(5):
        c = measure_repo(tmp_path, lvl)
        assert sum(c.values()) == 3, f"level {lvl} lost or duplicated a site"


def test_measure_repo_recovers_more_as_the_level_rises(tmp_path):
    (tmp_path / "m.py").write_text(
        "from crewai import Agent\n"
        "def mk():\n    return 'You are a reviewer auditing reports for issues.'\n"
        'a = Agent(role=mk(), goal="Find issues", backstory="Fifteen years of triage.")\n',
        encoding="utf-8",
    )
    got = [measure_repo(tmp_path, lvl)["static"] for lvl in range(5)]
    assert got == sorted(got)
    assert got[2] > got[0], "L2 should resolve the local callee L0 cannot"


def test_measure_repo_on_empty_tree(tmp_path):
    assert sum(measure_repo(tmp_path, 4).values()) == 0

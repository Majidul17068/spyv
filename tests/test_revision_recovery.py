"""Semantic regressions discovered in the paper audit."""

import pytest

from spyv.bench.visibility import sites_in_source


def calls(src, **kwargs):
    return [s for s in sites_in_source(src, "case.py", **kwargs) if s.construct == "kwarg.instructions"]


@pytest.mark.parametrize(
    "src",
    [
        'x="old"\nx=build()\nAgent(instructions=x)',
        'x="global"\ndef f(x):\n return Agent(instructions=x)',
        'def f():\n x="private"\ndef g():\n return Agent(instructions=x)',
        'Agent(instructions=x)\nx="future"',
        'x="old"\nimport unknown as x\nAgent(instructions=x)',
        'x="old"\nfor x in values:\n pass\nAgent(instructions=x)',
        'x="old"\nx += "more"\nAgent(instructions=x)',
        'x="old"\ndel x\nAgent(instructions=x)',
        'x="old"\ndef f():\n global x\n x=build()\ndef g():\n return Agent(instructions=x)',
        'class C:\n x="class"\n def f(self):\n  return Agent(instructions=x)',
        'x="literal"\nAgent(instructions=obj.x)',
        'if flag:\n x="conditional"\nAgent(instructions=x)',
        'x="global"\na=[Agent(instructions=x) for x in values]',
        'x="old"\nfrom unknown import *\nAgent(instructions=x)',
        'x="old"\nexec(code)\nAgent(instructions=x)',
        'x="old"\nglobals()["x"]=value\nAgent(instructions=x)',
        'x="old"\nf=lambda x: Agent(instructions=x)',
    ],
)
def test_unsafe_name_recovery_is_unknown(src):
    assert calls(src)[0].visibility == "opaque"


def test_same_named_locals_resolve_in_their_own_scope():
    src = 'def f():\n x="A"\n return Agent(instructions=x)\ndef g():\n x="B"\n return Agent(instructions=x)'
    assert [s.text for s in calls(src)] == ["A", "B"]


def test_same_line_calls_remain_distinct():
    s = calls('Agent(instructions="A"); Agent(instructions="B")')
    assert [x.text for x in s] == ["A", "B"]
    assert s[0].call_col != s[1].call_col


def test_concat_text_agrees_with_static_classification():
    s = calls('x="literal"\nAgent(instructions="prefix "+x)')[0]
    assert (s.visibility, s.text) == ("static", "prefix literal")


def test_empty_concat_does_not_invent_hole():
    s = calls('Agent(instructions=""+"literal")')[0]
    assert (s.visibility, s.text) == ("static", "literal")


def test_global_literal_available_in_function():
    assert calls('x="global"\ndef f():\n return Agent(instructions=x)')[0].text == "global"


def test_literal_baseline_shares_inventory_but_does_not_follow_names():
    src = 'x="text"\nAgent(instructions=x)'
    assert calls(src)[0].text == "text"
    assert calls(src, literal_only=True)[0].visibility == "opaque"


def test_default_expression_uses_outer_scope():
    src = 'x="outer"\ndef f(x=Agent(instructions=x)):\n pass'
    assert calls(src)[0].text == "outer"


def test_later_global_not_propagated_into_early_function():
    assert calls('def f():\n Agent(instructions=x)\nf()\nx="later"')[0].visibility == "opaque"


def test_walrus_in_comprehension_invalidates_outer_binding():
    src = 'x="old"\n[(x := dynamic()) for _ in xs]\nAgent(instructions=x)'
    assert calls(src)[0].visibility == "opaque"


def test_literal_placeholder_is_not_interpolation():
    site = calls('x="literal {...}"\nAgent(instructions=x)')[0]
    assert site.visibility == "static"
    assert site.text == "literal {...}"


def test_binding_interpolation_retains_partial_provenance():
    assert calls('x=f"prefix {dynamic()}"\nAgent(instructions=x)')[0].visibility == "partial"

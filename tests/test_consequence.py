"""Opacity-consequence experiment, per PROTOCOL_CONSEQUENCE.md."""

from __future__ import annotations

from spyv.bench.consequence import evaluate, ground_truth
from spyv.bench.runtime import Observation
from spyv.bench.visibility import PromptSite


def _site(line=2, vis="partial", construct="Agent.role", file="a.py"):
    return PromptSite(file=file, line=line, framework="crewai", construct=construct,
                      visibility=vis, text="hi {...}", call_line=1, call_end_line=4)


def _obs(text, line=1, construct="Agent.role", stack=None, file="a.py"):
    stack = stack or [[file, line]]
    return Observation(file=stack[0][0], line=stack[0][1], construct=construct,
                       text=text, stack=[list(f) for f in stack])


# --- verdicts ---------------------------------------------------------------


def test_two_distinct_strings_is_interpolating():
    ev, _ = ground_truth([_obs("a"), _obs("b")], [_site()])
    assert [e.verdict for e in ev.values()] == ["interpolating"]


def test_same_string_twice_is_constant():
    ev, _ = ground_truth([_obs("a"), _obs("a")], [_site()])
    assert [e.verdict for e in ev.values()] == ["constant"]


def test_single_observation_is_undetermined():
    """One observation cannot distinguish a constant from a variable."""
    ev, _ = ground_truth([_obs("a")], [_site()])
    assert [e.verdict for e in ev.values()] == ["undetermined"]
    r = evaluate([_obs("a")], [_site()])
    assert r["undetermined"] == 1
    assert r["interpolating"] == 0


# --- the attribution fix the protocol names ---------------------------------


def test_framework_reuse_does_not_manufacture_an_interpolating_site():
    """Many callers flowing through one library line is not one varying site.

    Grouping by innermost frame would score this as a single site with two
    distinct strings; grouping by authoring site correctly yields two constant
    sites.
    """
    sites = [_site(line=2, file="caller_a.py"), _site(line=2, file="caller_b.py")]
    obs = [
        _obs("role A", stack=[["lib/base.py", 775], ["caller_a.py", 1]]),
        _obs("role A", stack=[["lib/base.py", 775], ["caller_a.py", 1]]),
        _obs("role B", stack=[["lib/base.py", 775], ["caller_b.py", 1]]),
        _obs("role B", stack=[["lib/base.py", 775], ["caller_b.py", 1]]),
    ]
    r = evaluate(obs, sites)
    assert r["interpolating"] == 0
    assert r["constant"] == 2


# --- scoring ----------------------------------------------------------------


def test_partial_site_counts_as_detected():
    r = evaluate([_obs("a"), _obs("b")], [_site(vis="partial")])
    assert r["detected"] == 1 and r["missed_opaque"] == 0


def test_opaque_miss_is_separated_from_misjudged_static_miss():
    """Only the opaque half supports a structural claim."""
    sites = [_site(file="o.py", vis="opaque"), _site(file="s.py", vis="static")]
    obs = [_obs("a", file="o.py"), _obs("b", file="o.py"),
           _obs("c", file="s.py"), _obs("d", file="s.py")]
    r = evaluate(obs, sites)
    assert r["missed_opaque"] == 1
    assert r["missed_read_but_judged_constant"] == 1
    assert r["detected"] == 0


def test_no_rate_is_reported_below_the_threshold():
    r = evaluate([_obs("a"), _obs("b")], [_site()])
    assert r["enough_for_a_rate"] is False
    assert r["recall"] is None
    assert "single-digit" in r["note"]


def test_rate_is_reported_once_the_threshold_is_met():
    sites, obs = [], []
    for i in range(12):
        f = f"f{i}.py"
        sites.append(_site(file=f, vis="partial" if i < 9 else "opaque"))
        obs += [_obs("a", file=f), _obs(f"b{i}", file=f)]
    r = evaluate(obs, sites)
    assert r["enough_for_a_rate"] is True
    assert r["interpolating"] == 12
    assert r["detected"] == 9
    assert r["recall"] == 9 / 12
    assert r["share_of_misses_structural"] == 1.0


def test_unrelated_prompts_in_one_file_are_not_fused_into_interpolation():
    """The artifact this experiment is most vulnerable to.

    Two distinct Task(...) constructions in one test file, each with its own
    constant prompt. Without the line-span check both collapse onto whichever
    site is nearest, and the pair looks like one site interpolating two values.
    """
    sites = [
        PromptSite(file="t.py", line=10, framework="crewai", construct="Task.description",
                   visibility="static", text="alpha", call_line=9, call_end_line=11),
        PromptSite(file="t.py", line=90, framework="crewai", construct="Task.description",
                   visibility="static", text="beta", call_line=89, call_end_line=91),
    ]
    obs = [
        _obs("alpha", construct="Task.description", stack=[["t.py", 9]], file="t.py"),
        _obs("alpha", construct="Task.description", stack=[["t.py", 9]], file="t.py"),
        _obs("beta", construct="Task.description", stack=[["t.py", 89]], file="t.py"),
        _obs("beta", construct="Task.description", stack=[["t.py", 89]], file="t.py"),
    ]
    r = evaluate(obs, sites)
    assert r["interpolating"] == 0, "two constant sites must not fuse into one varying site"
    assert r["constant"] == 2


def test_observation_outside_every_span_is_counted_not_attributed():
    sites = [PromptSite(file="t.py", line=10, framework="crewai",
                        construct="Task.description", visibility="static",
                        text="alpha", call_line=9, call_end_line=11)]
    obs = [_obs("x", construct="Task.description", stack=[["t.py", 900]], file="t.py")]
    r = evaluate(obs, sites)
    assert r["observations_not_line_resolvable"] == 1
    assert r["sites_with_runtime_evidence"] == 0

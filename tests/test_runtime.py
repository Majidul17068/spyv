"""Runtime capture: stack attribution, span matching, and the validation diff."""

from __future__ import annotations

import copy

from spyv.bench.runtime import Observation, compare
from spyv.bench.visibility import PromptSite, sites_in_source


def _obs(construct, text, stack, ):
    return Observation(file=stack[0][0], line=stack[0][1], construct=construct,
                       text=text, stack=[list(f) for f in stack])


def _site(file="a.py", line=2, construct="Agent.role", vis="static", text="Analyst",
          call_line=1, call_end_line=4):
    return PromptSite(file=file, line=line, framework="crewai", construct=construct,
                      visibility=vis, text=text, call_line=call_line,
                      call_end_line=call_end_line)


# --- call spans -------------------------------------------------------------


def test_multiline_call_records_span_covering_every_argument():
    src = 'Agent(\n    role="Analyst",\n    goal="Report",\n)\n'
    sites = sites_in_source(src, "a.py")
    assert sites, "expected sites"
    for s in sites:
        assert s.call_line == 1 and s.call_end_line == 4
        assert s.call_line <= s.line <= s.call_end_line


def test_runtime_line_at_call_start_matches_argument_on_a_later_line():
    # The frame reports the line of `Agent(`; the site points at the kwarg.
    site = _site(line=3, call_line=1, call_end_line=4)
    r = compare([_obs("Agent.role", "Analyst", [("a.py", 1)])], [site])
    assert r["recovery"]["exact"] == 1
    assert r["recovery"]["wrong"] == 0


# --- stack attribution ------------------------------------------------------


def test_framework_rematerialisation_traces_to_the_authoring_frame():
    """A library rebuilding a user's object must not count as a missed site."""
    site = _site(file="test_x.py", line=2, call_line=1, call_end_line=3)
    obs = _obs("Agent.role", "Analyst",
               [("lib/base_agent.py", 775), ("test_x.py", 1)])
    r = compare([obs], [site])
    assert r["observed_but_not_enumerated"] == 0
    assert r["matched_via_framework_reuse"] == 1
    assert r["matched_at_authoring_frame"] == 0
    assert r["recovery"]["exact"] == 1


def test_authoring_frame_is_reported_separately_from_reuse():
    site = _site(file="a.py")
    r = compare([_obs("Agent.role", "Analyst", [("a.py", 1)])], [site])
    assert r["matched_at_authoring_frame"] == 1
    assert r["matched_via_framework_reuse"] == 0


def test_prompt_from_an_unenumerated_file_is_a_genuine_miss():
    obs = _obs("Agent.role", "loaded from yaml", [("loader.py", 40)])
    r = compare([obs], [_site(file="a.py")])
    assert r["observed_but_not_enumerated"] == 1
    assert r["recall_of_site_enumeration"] == 0.0


# --- scoring discipline -----------------------------------------------------


def test_observation_outside_every_span_is_not_scored():
    """Text equality off-span would be a coincidence of file contents."""
    site = _site(line=2, call_line=1, call_end_line=4)
    r = compare([_obs("Agent.role", "Analyst", [("a.py", 900)])], [site])
    assert r["recovery"]["not_line_resolvable"] == 1
    assert r["recovery"]["exact"] == 0
    assert r["recovery"]["wrong"] == 0


def test_opaque_site_is_excluded_from_correctness():
    site = _site(vis="opaque", text="")
    r = compare([_obs("Agent.role", "anything", [("a.py", 1)])], [site])
    assert r["recovery"]["site_was_opaque"] == 1
    assert r["recovery"]["correctness"] is None


def test_skeleton_site_accepts_a_consistent_runtime_string():
    site = _site(vis="partial", text="Answer as {...} today")
    r = compare([_obs("Agent.role", "Answer as a doctor today", [("a.py", 1)])], [site])
    assert r["recovery"]["skeleton_consistent"] == 1


def test_wrong_recovery_is_reported_as_wrong():
    r = compare([_obs("Agent.role", "Chemist", [("a.py", 1)])], [_site(text="Analyst")])
    assert r["recovery"]["wrong"] == 1
    assert r["recovery"]["correctness"] == 0.0


# --- negative control -------------------------------------------------------


def test_corrupting_static_text_degrades_correctness_monotonically():
    """Guards against a vacuous harness that reports 100% regardless of input.

    A comparison that filters observations by line span could in principle only
    ever score self-consistent pairs. Injecting known-wrong text must show up.
    """
    sites = [_site(file="a.py", line=i, call_line=i, call_end_line=i,
                   text=f"prompt {i}") for i in range(20)]
    obs = [_obs("Agent.role", f"prompt {i}", [("a.py", i)]) for i in range(20)]
    assert compare(obs, sites)["recovery"]["correctness"] == 1.0

    scores = []
    for k in (5, 10, 20):
        mutated = copy.deepcopy(sites)
        for s in mutated[:k]:
            s.text = "CORRUPTED"
        scores.append(compare(obs, mutated)["recovery"]["correctness"])
    assert scores == sorted(scores, reverse=True)
    assert scores[0] < 1.0 and scores[-1] == 0.0


# --- the injected hook must survive a foreign virtualenv ---------------------


def test_runtime_module_loads_by_path_without_importing_spyv():
    """Capture runs inside the subject repo's venv, which lacks spyv's deps.

    Importing spyv.bench.runtime pulls in spyv/__init__.py and the console
    stack, so the hooks died with ModuleNotFoundError('rich') in every venv
    that did not happen to install rich, and reported zero observations.
    Registering in sys.modules is required too: @dataclass resolves its own
    module through sys.modules[cls.__module__] while processing the class.
    """
    import importlib.util
    import sys
    from pathlib import Path

    source = Path(__import__("spyv.bench.runtime", fromlist=["x"]).__file__)
    name = "_spyv_runtime_isolated"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        assert module.Recorder is not None
        assert callable(module.install)
        rec = module.Recorder()
        rec.add("Agent.role", "hello")
        assert len(rec.observations) == 1
    finally:
        sys.modules.pop(name, None)


def test_injected_sitecustomize_registers_the_module_before_executing():
    """Guards the ordering, which is what actually broke."""
    from spyv.bench.runtime import _SITECUSTOMIZE

    body = _SITECUSTOMIZE
    assert "sys.modules[" in body
    assert body.index("sys.modules[") < body.index("exec_module")

    # It must not reach for the spyv package inside the subject's interpreter.
    # Checked on code lines only: the comments deliberately mention the import
    # they exist to warn against.
    code = "\n".join(ln for ln in body.splitlines()
                      if not ln.lstrip().startswith(("#", '"""')))
    assert "import spyv" not in code and "from spyv" not in code

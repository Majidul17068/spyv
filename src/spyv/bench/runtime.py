"""Runtime ground truth: what prompt text actually materialises when code runs.

Every figure in the static study rests on two unverified premises -- that the
sites we enumerate are prompt sites, and that the text we recover at them is
correct. Neither can be settled by more static analysis, because both are claims
*about* the static analysis. They need an independent observation of what the
program actually does.

This captures that observation without calling any model. Agent frameworks build
their prompts in ordinary constructors, and repositories exercise those
constructors in their own test suites. Wrapping the constructors and running the
tests yields real prompt strings, with the source location that produced them,
for the cost of a pytest run. No API key, no network, no inference spend.

What the comparison then supports:

    observed but never enumerated   a site the static pass missed  -> recall
    enumerated, text differs         recovery is wrong             -> correctness
    enumerated, never observed       candidate false positive, weakly:
                                     a site may simply be untested

The third is deliberately weak and is reported as such. A site that no test
exercises is not thereby a false positive, and treating it as one would
manufacture a precision figure the design cannot support.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MAX_TEXT = 4000
# Frames inside these are framework internals, not the caller we want to attribute to.
_SKIP_FRAME_MARKERS = ("site-packages", "/lib/python", "spyv/bench/runtime.py")


@dataclass
class Observation:
    """One prompt string that actually materialised, and where it came from."""

    file: str
    line: int
    construct: str
    text: str
    # Every first-party frame, innermost first. A framework that re-materialises
    # a user's object (copying role/goal into a fresh Agent internally) produces
    # a second observation whose innermost frame is library code. That is the
    # same authored prompt seen twice, not a site the static pass missed, so
    # tracing needs the whole stack rather than one frame.
    stack: list[list[Any]] = field(default_factory=list)

    def key(self) -> tuple[str, str]:
        return (self.file, self.construct)


@dataclass
class Recorder:
    observations: list[Observation] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)

    def add(self, construct: str, text: Any) -> None:
        if not isinstance(text, str) or not text.strip():
            return
        stack = _caller_stack()
        if not stack:
            self.errors["no_attributable_frame"] += 1
            return
        path, line = stack[0]
        self.observations.append(
            Observation(file=path, line=line, construct=construct,
                        text=text[:MAX_TEXT], stack=[[f, ln] for f, ln in stack])
        )


def _caller_frame() -> tuple[str, int] | None:
    """The innermost frame outside stdlib and our own hook code."""
    for name, line in _caller_stack():
        return name, line
    return None


def _caller_stack(limit: int = 40) -> list[tuple[str, int]]:
    """Every first-party frame, innermost first.

    Attribution matters: a naive `sys._getframe(1)` lands inside the framework's
    own constructor, which is never where the prompt was written. Returning the
    whole stack lets the caller decide which frame authored the text.
    """
    out: list[tuple[str, int]] = []
    try:
        frame: Any = sys._getframe(2)
    except ValueError:  # pragma: no cover - stack shallower than expected
        return out
    while frame is not None and len(out) < limit:
        name = frame.f_code.co_filename
        if not any(marker in name for marker in _SKIP_FRAME_MARKERS):
            out.append((name, frame.f_lineno))
        frame = frame.f_back
    return out


# ---------------------------------------------------------------------------
# hooks
# ---------------------------------------------------------------------------
_CREWAI_AGENT_FIELDS = ("role", "goal", "backstory")
_CREWAI_TASK_FIELDS = ("description", "expected_output")
_GENERIC_KWARGS = ("system_prompt", "system_message", "system_instruction",
                   "instructions", "preamble", "persona")


def _wrap_init(cls: Any, fields: tuple[str, ...], prefix: str, rec: Recorder) -> Any:
    original = cls.__init__

    def patched(self: Any, *args: Any, **kwargs: Any) -> Any:
        for f in fields:
            if f in kwargs:
                rec.add(f"{prefix}.{f}", kwargs[f])
        return original(self, *args, **kwargs)

    cls.__init__ = patched
    return original


def install(rec: Recorder) -> list[tuple[Any, str, Any]]:
    """Patch whatever prompt-bearing constructors are importable. Returns undo state.

    Deliberately best-effort: a repository that does not use CrewAI should not
    fail to be measured because CrewAI is absent.
    """
    undo: list[tuple[Any, str, Any]] = []

    try:
        import crewai  # type: ignore

        undo.append((crewai.Agent, "__init__",
                     _wrap_init(crewai.Agent, _CREWAI_AGENT_FIELDS, "Agent", rec)))
        undo.append((crewai.Task, "__init__",
                     _wrap_init(crewai.Task, _CREWAI_TASK_FIELDS, "Task", rec)))
    except Exception:
        rec.errors["crewai_unavailable"] += 1

    try:
        from langchain_core import messages as lc  # type: ignore

        original = lc.SystemMessage.__init__

        def patched_sys(self: Any, content: Any = "", *a: Any, **kw: Any) -> Any:
            rec.add("SystemMessage", content)
            return original(self, content, *a, **kw)

        lc.SystemMessage.__init__ = patched_sys
        undo.append((lc.SystemMessage, "__init__", original))
    except Exception:
        rec.errors["langchain_unavailable"] += 1

    # OpenAI chat completions: the system message is the prompt that ships.
    try:
        from openai.resources.chat import completions as oc  # type: ignore

        original_create = oc.Completions.create

        def patched_create(self: Any, *a: Any, **kw: Any) -> Any:
            for msg in kw.get("messages", []) or []:
                if isinstance(msg, dict) and msg.get("role") == "system":
                    rec.add("message.system", msg.get("content"))
            return original_create(self, *a, **kw)

        oc.Completions.create = patched_create
        undo.append((oc.Completions, "create", original_create))
    except Exception:
        rec.errors["openai_unavailable"] += 1

    return undo


def uninstall(undo: list[tuple[Any, str, Any]]) -> None:
    for owner, attr, original in undo:
        with contextlib.suppress(Exception):
            setattr(owner, attr, original)


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    return " ".join(text.split())


def _skeleton_matches(static_text: str, runtime_text: str) -> bool:
    """Does a partial recovery's literal skeleton appear in the runtime string?

    A `partial` site recovers a template with holes marked `{...}`. The honest
    test is whether every literal fragment survives, in order, in the text the
    program actually produced.
    """
    fragments = [f for f in _norm(static_text).split("{...}") if f.strip()]
    if not fragments:
        return False
    hay = _norm(runtime_text)
    pos = 0
    for frag in fragments:
        idx = hay.find(frag.strip(), pos)
        if idx < 0:
            return False
        pos = idx + len(frag.strip())
    return True


def _site_matches_line(site: Any, line: int) -> bool:
    """Does a runtime line fall inside this site's enclosing expression?"""
    start = getattr(site, "call_line", 0) or site.line
    end = getattr(site, "call_end_line", 0) or site.line
    return start <= line <= end


def _resolve(obs: Observation, by_key: dict[tuple[str, str], list[Any]]) -> tuple[Any, int] | None:
    """Find the enumerated site that authored this prompt.

    Walks the observation's stack innermost-first and returns the first frame
    whose file and construct were enumerated, preferring a site whose call span
    contains the frame's line. Returning the frame depth lets the caller tell an
    authored site (depth 0) from one reached through framework re-materialisation.
    """
    frames = obs.stack or [[obs.file, obs.line]]
    for depth, entry in enumerate(frames):
        path, line = entry[0], entry[1]
        candidates = by_key.get((path, obs.construct))
        if not candidates:
            continue
        spanned = [c for c in candidates if _site_matches_line(c, line)]
        if spanned:
            return min(spanned, key=lambda c: abs((c.line or 0) - line)), depth
        return min(candidates, key=lambda c: abs((c.line or 0) - line)), depth
    return None


def compare(observations: list[Observation], sites: list[Any]) -> dict[str, Any]:
    """Diff runtime observations against static sites."""
    by_key: dict[tuple[str, str], list[Any]] = {}
    for s in sites:
        by_key.setdefault((s.file, s.construct), []).append(s)

    matched = missed = 0
    direct = 0  # matched at stack depth 0: the frame that wrote the text
    exact = skeleton = wrong = unknown = 0
    unspanned = 0  # matched file+construct but no site covering that line
    examples: list[dict[str, Any]] = []

    for obs in observations:
        found = _resolve(obs, by_key)
        if found is None:
            missed += 1
            if len(examples) < 25:
                examples.append({"kind": "missed_site", "file": obs.file,
                                 "line": obs.line, "construct": obs.construct,
                                 "runtime_text": obs.text[:160]})
            continue
        site, depth = found
        matched += 1
        if depth == 0:
            direct += 1
        frame_line = (obs.stack[depth][1] if obs.stack else obs.line)
        if not _site_matches_line(site, frame_line):
            # The prompt came from this file and construct, but no enumerated
            # expression spans the executing line. Text equality here would be
            # a coincidence of the file's contents, so it is not scored.
            unspanned += 1
            continue
        if site.visibility == "opaque" or not site.text:
            unknown += 1
        elif _norm(site.text) == _norm(obs.text):
            exact += 1
        elif "{...}" in site.text and _skeleton_matches(site.text, obs.text):
            skeleton += 1
        else:
            wrong += 1
            if len(examples) < 25:
                examples.append({"kind": "wrong_text", "file": site.file,
                                 "line": site.line, "construct": obs.construct,
                                 "static_text": site.text[:160],
                                 "runtime_text": obs.text[:160]})

    verified = exact + skeleton
    checkable = verified + wrong
    return {
        "observations": len(observations),
        "matched_to_a_static_site": matched,
        "matched_at_authoring_frame": direct,
        "matched_via_framework_reuse": matched - direct,
        "observed_but_not_enumerated": missed,
        "recall_of_site_enumeration": matched / len(observations) if observations else 0.0,
        "recovery": {
            "exact": exact,
            "skeleton_consistent": skeleton,
            "wrong": wrong,
            "site_was_opaque": unknown,
            "not_line_resolvable": unspanned,
            "correctness": verified / checkable if checkable else None,
            "note": ("Correctness is over sites where the static pass claimed text AND the "
                     "site was exercised AND an enumerated expression spans the executing "
                     "line. Opaque sites are excluded: they make no claim to be wrong about. "
                     "Observations that resolve only to a file and construct are counted in "
                     "not_line_resolvable rather than scored, since text equality would not "
                     "be attributable to a specific enumerated expression."),
        },
        "examples": examples,
    }


def save(rec: Recorder, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "observations": [asdict(o) for o in rec.observations],
        "hook_errors": dict(rec.errors),
    }, indent=2), encoding="utf-8")


def load(path: Path) -> list[Observation]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Observation(**o) for o in data["observations"]]


__all__ = ["Observation", "Recorder", "compare", "install", "load", "save", "uninstall"]


# ---------------------------------------------------------------------------
# running a repository's own test suite under the hooks
# ---------------------------------------------------------------------------
_SITECUSTOMIZE = '''"""Injected by spyv to capture prompt construction. Not part of the project."""
import atexit, json, os, sys

sys.path.insert(0, {spyv_src!r})
try:
    from spyv.bench.runtime import Recorder, install, save
    from pathlib import Path

    _rec = Recorder()
    install(_rec)

    @atexit.register
    def _dump():
        try:
            save(_rec, Path({out!r}))
        except Exception:
            pass
except Exception as exc:  # capture must never break the suite it observes
    sys.stderr.write("spyv runtime hook failed: %r\\n" % (exc,))
'''


def run_test_suite(
    repo: str | Path,
    out: str | Path,
    *,
    python: str | None = None,
    timeout: int = 900,
    pytest_args: list[str] | None = None,
) -> dict[str, Any]:
    """Run a repository's own tests with the hooks installed.

    We capture through the project's test suite rather than by executing agents,
    because tests construct prompts without calling a model: no API key, no
    network, no inference cost. The suite does not need to pass -- a collection
    error still exercises whatever imported cleanly, and partial capture is
    still ground truth for what it captured.
    """
    import subprocess
    import tempfile

    repo_path = Path(repo).resolve()
    out_path = Path(out).resolve()
    spyv_src = str(Path(__file__).resolve().parents[2])

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "sitecustomize.py").write_text(
            _SITECUSTOMIZE.format(spyv_src=spyv_src, out=str(out_path)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = tmp + os.pathsep + env.get("PYTHONPATH", "")
        # Keep a stray key from turning a capture run into real API calls.
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
            env.pop(key, None)
        env["SPYV_RUNTIME_CAPTURE"] = "1"

        cmd = [python or sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               *(pytest_args or []), "--co" if False else ""]
        cmd = [c for c in cmd if c]
        try:
            proc = subprocess.run(cmd, cwd=repo_path, env=env, capture_output=True,
                                  text=True, timeout=timeout, check=False)
            status, tail = proc.returncode, (proc.stdout or "")[-800:]
        except subprocess.TimeoutExpired:
            status, tail = -1, "timeout"
        except OSError as exc:
            status, tail = -2, repr(exc)

    captured = 0
    if out_path.exists():
        try:
            captured = len(json.loads(out_path.read_text(encoding="utf-8"))["observations"])
        except (OSError, ValueError, KeyError):
            captured = 0
    return {"repo": repo_path.name, "exit_code": status, "observations": captured, "tail": tail}

"""Resolving prompts passed by variable rather than as a literal.

Real code assembles a prompt into a local and passes the name, which leaves the
call site holding an ast.Name. Without one hop through the binding, a whole
codebase of Task(description=description) looks prompt-free.
"""

from __future__ import annotations

from spyv.discovery import discover

_LONG = (
    "You are a triage reviewer. Read the incident report and list every issue that is "
    "not already resolved, with a severity for each."
)
_OTHER = (
    "You are a ledger assistant. Reconcile the invoice against the purchase order "
    "and report any discrepancy you find."
)
_OUT = "A markdown list of issues, each with a severity and a suggested remediation."


def _discover(tmp_path, body: str):
    (tmp_path / "m.py").write_text(body, encoding="utf-8")
    return discover(tmp_path)[0]


def test_description_bound_to_a_local_is_resolved(tmp_path):
    prompts = _discover(
        tmp_path,
        "from crewai import Task\n"
        f'description = "{_LONG}"\n'
        f't = Task(description=description, expected_output="{_OUT}")\n',
    )
    tasks = [p for p in prompts if p.source_kind == "crewai_task"]
    assert len(tasks) == 1
    assert "triage reviewer" in tasks[0].system_prompt


def test_fstring_bound_to_a_local_is_resolved(tmp_path):
    """The common real-world shape: an f-string assigned, then passed by name."""
    prompts = _discover(
        tmp_path,
        "from crewai import Task\n"
        "ctx = get_context()\n"
        f'description = f"{_LONG} Context: {{ctx}}"\n'
        f't = Task(description=description, expected_output="{_OUT}")\n',
    )
    tasks = [p for p in prompts if p.source_kind == "crewai_task"]
    assert len(tasks) == 1
    assert "{...}" in tasks[0].system_prompt, "the interpolated hole should be marked"


def test_attribute_binding_resolves_conservatively(tmp_path):
    prompts = _discover(
        tmp_path,
        "from crewai import Task\n"
        "class T:\n"
        "    def build(self):\n"
        f'        self.description = "{_LONG}"\n'
        f'        return Task(description=self.description, expected_output="{_OUT}")\n',
    )
    assert [p for p in prompts if p.source_kind == "crewai_task"]


def test_a_name_bound_twice_to_the_same_text_still_resolves(tmp_path):
    prompts = _discover(
        tmp_path,
        "from crewai import Task\n"
        f'description = "{_LONG}"\n'
        f'description = "{_LONG}"\n'
        f't = Task(description=description, expected_output="{_OUT}")\n',
    )
    assert [p for p in prompts if p.source_kind == "crewai_task"]


def test_an_ambiguous_name_is_dropped_rather_than_guessed(tmp_path):
    """Attributing the wrong prompt to a call is worse than missing it."""
    prompts = _discover(
        tmp_path,
        "from crewai import Task\n"
        f'description = "{_LONG}"\n'
        f'description = "{_OTHER}"\n'
        f't = Task(description=description, expected_output="{_OUT}")\n',
    )
    assert not [p for p in prompts if p.source_kind == "crewai_task"]


def test_a_prompt_built_by_a_method_call_stays_unresolvable(tmp_path):
    """A boundary of static analysis, asserted so it is a known limit.

    The string does not exist until the method runs, so no static analyzer can
    see it. This is the case the runtime guard exists for.
    """
    prompts = _discover(
        tmp_path,
        "from crewai import Task\n"
        "class T:\n"
        "    def build(self):\n"
        f'        return Task(description=self._make(), expected_output="{_OUT}")\n',
    )
    assert not [p for p in prompts if p.source_kind == "crewai_task"]


def test_crewai_agent_fields_resolve_through_bindings_too(tmp_path):
    prompts = _discover(
        tmp_path,
        "from crewai import Agent\n"
        'role = "Triage reviewer"\n'
        'goal = "Find every unresolved issue in the record report"\n'
        'backstory = "You have audited reports for fifteen years and miss nothing."\n'
        "a = Agent(role=role, goal=goal, backstory=backstory)\n",
    )
    agents = [p for p in prompts if p.source_kind == "crewai_agent"]
    assert len(agents) == 1
    assert "Triage reviewer" in agents[0].system_prompt


def test_binding_does_not_invent_a_prompt_from_a_short_string(tmp_path):
    prompts = _discover(
        tmp_path,
        "from crewai import Task\ndescription = \"Do it.\"\nt = Task(description=description)\n",
    )
    assert not [p for p in prompts if p.source_kind == "crewai_task"]


def test_unrelated_variable_is_not_pulled_into_a_call(tmp_path):
    """Only the kwarg actually referencing the name may resolve to it."""
    prompts = _discover(
        tmp_path,
        f'unused = "{_LONG}"\nw = Widget(size=10)\n',
    )
    assert not [p for p in prompts if p.source_kind == "crewai_task"]


# --- self-attribute recovery: sound only within one scope --------------------


def _recover(src: str) -> str | None:
    """Run discovery over one source string and return the recovered prompt."""
    import pathlib
    import tempfile

    from spyv.discovery import _from_python

    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "t.py"
    p.write_text(src)
    got = [g for g in _from_python(p, src) if g.source_kind != "python_var"]
    return got[0].system_prompt if got else None


_TMPL = (
    "class A:\n"
    "{setup}"
    "    def run(self{arg}):\n"
    "{body}"
    '        Agent(role=self.role_prompt, goal="Do the thing well", '
    'backstory="A backstory here")\n'
)


def test_self_attribute_recovered_within_one_method():
    src = _TMPL.format(setup="", arg="", body='        self.role_prompt = "SAFE-LITERAL"\n')
    assert "SAFE-LITERAL" in (_recover(src) or "")


def test_self_attribute_not_carried_across_methods():
    """__init__ assigns, run() reads. Another method may have mutated it since."""
    src = _TMPL.format(
        setup='    def __init__(self):\n        self.role_prompt = "FROM-INIT"\n',
        arg="",
        body="",
    )
    assert _recover(src) is None


def test_self_attribute_invalidated_by_reassignment():
    """The obsolete-literal bug: a later dynamic write must void the earlier one."""
    src = _TMPL.format(
        setup="",
        arg=", x",
        body='        self.role_prompt = "OBSOLETE"\n        self.role_prompt = x\n',
    )
    assert _recover(src) is None


def test_self_attribute_not_recovered_when_mutated_elsewhere():
    src = _TMPL.format(
        setup=(
            '    def __init__(self):\n        self.role_prompt = "STALE"\n'
            "    def mutate(self, x):\n        self.role_prompt = x\n"
        ),
        arg="",
        body="",
    )
    assert _recover(src) is None

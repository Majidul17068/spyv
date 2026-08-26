"""CrewAI Task discovery.

Task(description=..., expected_output=...) is prompt surface: both strings are
sent to the model. Neither field name is in _NAME_HINTS, so before this was
added a Task-heavy codebase looked prompt-free to discovery.
"""

from __future__ import annotations

from spyv.discovery import discover

_LONG = (
    "Review the incident report and identify every unresolved issue that is not already "
    "addressed, then summarise each one for the on-call engineer."
)
_OUT = "A markdown list of issues, each with a severity and a suggested remediation."


def _write(tmp_path, body: str):
    (tmp_path / "tasks.py").write_text(body, encoding="utf-8")
    return discover(tmp_path)[0]


def test_task_with_description_and_expected_output_is_discovered(tmp_path):
    prompts = _write(
        tmp_path,
        f'from crewai import Task\nt = Task(description="{_LONG}", expected_output="{_OUT}")\n',
    )
    tasks = [p for p in prompts if p.source_kind == "crewai_task"]
    assert len(tasks) == 1
    assert "DESCRIPTION:" in tasks[0].system_prompt
    assert "EXPECTED OUTPUT:" in tasks[0].system_prompt
    assert _OUT in tasks[0].system_prompt


def test_named_task_call_needs_only_a_description(tmp_path):
    prompts = _write(tmp_path, f'from crewai import Task\nt = Task(description="{_LONG}")\n')
    assert [p for p in prompts if p.source_kind == "crewai_task"]


def test_module_qualified_task_is_discovered(tmp_path):
    prompts = _write(tmp_path, f'import crewai\nt = crewai.Task(description="{_LONG}")\n')
    assert [p for p in prompts if p.source_kind == "crewai_task"]


def test_conditional_task_is_discovered(tmp_path):
    prompts = _write(
        tmp_path, f'from crewai import ConditionalTask\nt = ConditionalTask(description="{_LONG}")\n'
    )
    assert [p for p in prompts if p.source_kind == "crewai_task"]


def test_unrelated_call_with_a_bare_description_is_not_a_prompt(tmp_path):
    """Precision guard: matching every description= kwarg would flood the report."""
    prompts = _write(tmp_path, f'w = Widget(description="{_LONG}")\n')
    assert not [p for p in prompts if p.source_kind == "crewai_task"]


def test_description_expected_output_pair_is_enough_without_the_task_name(tmp_path):
    """The pair is characteristic of CrewAI even when the call is aliased."""
    prompts = _write(tmp_path, f'w = make(description="{_LONG}", expected_output="{_OUT}")\n')
    assert [p for p in prompts if p.source_kind == "crewai_task"]


def test_short_description_is_below_the_precision_floor(tmp_path):
    prompts = _write(tmp_path, 'from crewai import Task\nt = Task(description="Do it.")\n')
    assert not [p for p in prompts if p.source_kind == "crewai_task"]


def test_identifier_is_the_first_line_of_the_description(tmp_path):
    prompts = _write(
        tmp_path,
        'from crewai import Task\nt = Task(description="""Audit the report.\nThen report every gap you can find in it.""")\n',
    )
    tasks = [p for p in prompts if p.source_kind == "crewai_task"]
    assert tasks
    assert tasks[0].identifier == "Audit the report."


def test_agent_still_wins_over_task_when_role_and_goal_are_present(tmp_path):
    """Regression: an Agent must not be reclassified as a task."""
    prompts = _write(
        tmp_path,
        'from crewai import Agent\n'
        'a = Agent(role="Triage reviewer", goal="Find unresolved issues in the report", '
        'backstory="You have triaged incident reports for fifteen years and miss nothing.")\n',
    )
    kinds = {p.source_kind for p in prompts}
    assert "crewai_agent" in kinds
    assert "crewai_task" not in kinds


def test_task_and_agent_in_one_file_are_both_found(tmp_path):
    prompts = _write(
        tmp_path,
        'from crewai import Agent, Task\n'
        'a = Agent(role="Triage reviewer", goal="Find unresolved issues in the report", '
        'backstory="You have triaged incident reports for fifteen years and miss nothing.")\n'
        f't = Task(description="{_LONG}", expected_output="{_OUT}")\n',
    )
    kinds = [p.source_kind for p in prompts]
    assert "crewai_agent" in kinds
    assert "crewai_task" in kinds

"""`--out` must write a file in every format the CLI offers.

`_write_out` called `terminal.render_text` and `terminal.render_markdown`,
neither of which existed. `--format json` worked, so the broken branches were
the default one and `md`. Nothing exercised them, and the call site catches only
OSError, so the AttributeError would have surfaced as a traceback.
"""

from __future__ import annotations

import json

import pytest

from spyv.cli import _write_out
from spyv.contracts import (
    GuardrailAudit,
    MissingGuardrail,
    OptimizationReport,
    QualityReport,
    Report,
    SpyvFinding,
    Vulnerability,
)


def _report() -> Report:
    return Report(
        target_hash="abc123",
        model_used="test-model",
        reason_checksum="deadbeef",
        generated_at="2026-11-10T00:00:00Z",
        overall_score=42.5,
        overall_verdict="fix_first",
        quality=QualityReport(
            score=50.0,
            findings=[SpyvFinding(id="q1", pillar="quality", severity="medium",
                                  title="Ambiguous instruction", description="unclear")],
            strengths=["Scopes the task"],
        ),
        optimization=OptimizationReport(score=60.0, total_tokens=120),
        vulnerabilities=[Vulnerability(
            id="v1", category="injection", severity="high",
            owasp_llm_tag="LLM01", title="Prompt injection", description="user text is trusted",
        )],
        guardrails=GuardrailAudit(
            score=30.0,
            missing=[MissingGuardrail(kind="output_filter", severity="high",
                                      suggested_text="add one")],
        ),
    )


@pytest.mark.parametrize("fmt", ["text", "md", "json"])
def test_every_format_writes_a_file(tmp_path, fmt):
    path = tmp_path / f"report.{fmt}"
    _write_out(_report(), path, fmt)
    assert path.exists() and path.stat().st_size > 0


def test_json_output_round_trips(tmp_path):
    path = tmp_path / "r.json"
    _write_out(_report(), path, "json")
    assert json.loads(path.read_text(encoding="utf-8"))["target_hash"] == "abc123"


@pytest.mark.parametrize("fmt", ["text", "md"])
def test_human_formats_carry_the_findings(tmp_path, fmt):
    """A written report is useless if it omits what was found."""
    path = tmp_path / f"r.{fmt}"
    _write_out(_report(), path, fmt)
    body = path.read_text(encoding="utf-8")

    assert "Prompt injection" in body
    assert "Ambiguous instruction" in body
    assert "output_filter" in body, "missing guardrail not reported"
    assert "fix_first" in body


def test_text_format_has_no_markup(tmp_path):
    """The file is read without a terminal, so no escape codes."""
    path = tmp_path / "r.txt"
    _write_out(_report(), path, "text")
    assert "\x1b[" not in path.read_text(encoding="utf-8")

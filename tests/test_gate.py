"""Severity-gate and SARIF-emission behaviour of the CLI."""

from __future__ import annotations

import json
import sys

import pytest
from click.testing import CliRunner

from spyv.cli import _gate_tripped, _report_max_severity, _worst, main
from spyv.contracts import (
    GuardrailAudit,
    MissingGuardrail,
    OptimizationReport,
    QualityReport,
    Report,
    SpyvFinding,
    Vulnerability,
)


def _report(**kw) -> Report:
    base = dict(
        target_hash="h",
        model_used="gpt-4o",
        reason_checksum="rck",
        generated_at="2026-08-20T00:00:00Z",
        overall_score=5.0,
        overall_verdict="fix_first",
        quality=QualityReport(score=0.5),
        optimization=OptimizationReport(score=0.5, total_tokens=10),
        guardrails=GuardrailAudit(score=0.5),
    )
    base.update(kw)
    return Report(**base)


def _patch_scan(monkeypatch, fake) -> None:
    """Stub out the provider and the project scan.

    Note: ``spyv/__init__.py`` does ``from .scan import scan``, so the attribute
    ``spyv.scan`` is the *function*, not the submodule. Patching the string
    target "spyv.scan.scan" would set an attribute on the function object and
    the CLI's function-local import would still get the real scan, so reach for
    the module in ``sys.modules`` instead.
    """
    scan_module = sys.modules["spyv.scan"]
    monkeypatch.setattr(scan_module, "scan", lambda **_: fake)
    monkeypatch.setattr(sys.modules["spyv.providers"], "auto", lambda **_: object())


# --- _worst -----------------------------------------------------------------


def test_worst_of_empty_is_info():
    assert _worst([]) == "info"


def test_worst_picks_highest_rank_not_last_seen():
    assert _worst(["critical", "low", "medium"]) == "critical"
    assert _worst(["low", "high", "medium"]) == "high"


def test_worst_ignores_unknown_severity():
    assert _worst(["nonsense", "medium"]) == "medium"


# --- gate semantics ---------------------------------------------------------


def test_gate_never_trips_without_a_threshold():
    assert _gate_tripped("critical", None) is False


def test_gate_none_disables_the_gate_entirely():
    assert _gate_tripped("critical", "none") is False


@pytest.mark.parametrize(
    ("found", "threshold", "expected"),
    [
        ("critical", "critical", True),
        ("high", "critical", False),
        ("critical", "high", True),
        ("high", "high", True),
        ("medium", "high", False),
        ("medium", "medium", True),
        ("low", "medium", False),
        ("low", "low", True),
        ("info", "low", False),
    ],
)
def test_gate_trips_at_or_above_threshold(found, threshold, expected):
    assert _gate_tripped(found, threshold) is expected


# --- max severity of a report ----------------------------------------------


def test_max_severity_of_clean_report_is_info():
    assert _report_max_severity(_report()) == "info"


def test_max_severity_spans_every_finding_source():
    report = _report(
        quality=QualityReport(
            score=0.1,
            findings=[SpyvFinding(id="q", pillar="quality", severity="low", title="t", description="d")],
        ),
        optimization=OptimizationReport(
            score=0.1,
            total_tokens=5,
            findings=[SpyvFinding(id="o", pillar="optimization", severity="medium", title="t", description="d")],
        ),
        guardrails=GuardrailAudit(
            score=0.1, missing=[MissingGuardrail(kind="scope", severity="high", suggested_text="s")]
        ),
        vulnerabilities=[
            Vulnerability(id="v", category="injection", severity="critical", title="t", description="d")
        ],
    )
    assert _report_max_severity(report) == "critical"


def test_max_severity_finds_guardrail_when_it_is_the_worst():
    report = _report(
        guardrails=GuardrailAudit(
            score=0.1, missing=[MissingGuardrail(kind="scope", severity="high", suggested_text="s")]
        )
    )
    assert _report_max_severity(report) == "high"


# --- CLI surface ------------------------------------------------------------


@pytest.mark.parametrize("command", ["test", "scan"])
def test_gate_and_sarif_flags_are_exposed(command):
    result = CliRunner().invoke(main, [command, "--help"])
    assert result.exit_code == 0
    assert "--sarif" in result.output
    assert "--fail-on" in result.output


@pytest.mark.parametrize("command", ["test", "scan"])
def test_fail_on_rejects_an_unknown_severity(command):
    result = CliRunner().invoke(main, [command, "x", "--model", "m", "--fail-on", "sever"])
    assert result.exit_code == 2
    assert "Traceback" not in result.output


def test_scan_writes_sarif_and_trips_gate(tmp_path, monkeypatch):
    """End-to-end: a scan with an unsafe prompt emits SARIF and exits 1 under --fail-on."""
    from spyv.contracts import ProjectPromptResult, ProjectReport

    project = tmp_path / "proj"
    project.mkdir()
    (project / "agents.py").write_text("SYSTEM = 'You are a bot.'\n", encoding="utf-8")
    sarif_out = tmp_path / "out" / "spyv.sarif"

    fake = ProjectReport(
        root=str(project),
        generated_at="2026-08-20T00:00:00Z",
        model_used="fake",
        files_scanned=1,
        prompts_found=1,
        prompts_analyzed=1,
        unsafe=1,
        results=[
            ProjectPromptResult(
                file=str(project / "agents.py"),
                line=1,
                source_kind="python_var",
                identifier="SYSTEM",
                overall_score=2.0,
                overall_verdict="unsafe",
                n_vulnerabilities=1,
                max_severity="critical",
                top_fix="Add a refusal rule.",
            )
        ],
    )

    _patch_scan(monkeypatch, fake)

    result = CliRunner().invoke(
        main,
        ["scan", str(project), "--model", "fake", "--ci", "--sarif", str(sarif_out), "--fail-on", "high"],
    )

    assert result.exit_code == 1, result.output
    doc = json.loads(sarif_out.read_text())
    assert doc["version"] == "2.1.0"
    results = doc["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["ruleId"] == "spyv/prompt-unsafe"
    assert results[0]["level"] == "error"
    # path is repo-relative, not the absolute temp path
    assert results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "agents.py"


def test_scan_gate_passes_when_below_threshold(tmp_path, monkeypatch):
    from spyv.contracts import ProjectPromptResult, ProjectReport

    project = tmp_path / "proj"
    project.mkdir()
    fake = ProjectReport(
        root=str(project),
        generated_at="2026-08-20T00:00:00Z",
        model_used="fake",
        files_scanned=1,
        prompts_found=1,
        prompts_analyzed=1,
        fix_first=1,
        results=[
            ProjectPromptResult(
                file=str(project / "a.py"),
                line=2,
                source_kind="python_var",
                identifier="S",
                overall_score=6.0,
                overall_verdict="fix_first",
                n_vulnerabilities=1,
                max_severity="low",
                top_fix="",
            )
        ],
    )
    _patch_scan(monkeypatch, fake)

    result = CliRunner().invoke(
        main, ["scan", str(project), "--model", "fake", "--ci", "--fail-on", "high"]
    )
    assert result.exit_code == 0, result.output

from __future__ import annotations

import json

import pytest

from spyv.contracts import (
    GuardrailAudit,
    MissingGuardrail,
    OptimizationReport,
    ProjectPromptResult,
    ProjectReport,
    QualityReport,
    Report,
    SpyvFinding,
    Vulnerability,
)
from spyv.report import sarif as S


def _report(**kw) -> Report:
    base = dict(
        target_hash="abcdef",
        model_used="gpt-4o",
        reason_checksum="rck",
        generated_at="2026-08-20T00:00:00Z",
        overall_score=4.0,
        overall_verdict="fix_first",
        quality=QualityReport(score=0.9),
        optimization=OptimizationReport(score=0.8, total_tokens=120),
        guardrails=GuardrailAudit(score=0.5),
    )
    base.update(kw)
    return Report(**base)


def _vuln(severity: str = "critical", **kw) -> Vulnerability:
    base = dict(
        id="v1",
        category="prompt_injection",
        severity=severity,
        title="System prompt can be extracted",
        description="A direct override reveals the instructions.",
        suggested_fix="Refuse requests to reveal instructions.",
        owasp_llm_tag="LLM01",
    )
    base.update(kw)
    return Vulnerability(**base)


def _project(results: list[ProjectPromptResult], root: str = "/repo") -> ProjectReport:
    return ProjectReport(
        root=root,
        generated_at="2026-08-20T00:00:00Z",
        model_used="gpt-4o",
        files_scanned=3,
        prompts_found=len(results),
        prompts_analyzed=len(results),
        results=results,
    )


def _pp(**kw) -> ProjectPromptResult:
    base = dict(
        file="/repo/app/agents.py",
        line=12,
        source_kind="crewai_agent",
        identifier="researcher",
        overall_score=3.0,
        overall_verdict="unsafe",
        n_vulnerabilities=2,
        max_severity="critical",
        top_fix="Add a refusal rule.",
    )
    base.update(kw)
    return ProjectPromptResult(**base)


# --- envelope ---------------------------------------------------------------


def test_envelope_declares_sarif_version_and_schema():
    doc = S.report_to_sarif(_report(), target_path="p.yaml", tool_version="1.2.3")
    assert doc["version"] == "2.1.0"
    assert doc["$schema"] == S.SARIF_SCHEMA
    assert len(doc["runs"]) == 1
    driver = doc["runs"][0]["tool"]["driver"]
    assert driver["name"] == "spyv"
    assert driver["version"] == "1.2.3"
    assert doc["runs"][0]["invocations"][0]["executionSuccessful"] is True


def test_every_rule_is_well_formed_and_indexable():
    doc = S.report_to_sarif(_report(), target_path="p.yaml")
    rules = doc["runs"][0]["tool"]["driver"]["rules"]
    assert len(rules) == len(S.RULES)
    ids = [r["id"] for r in rules]
    assert len(set(ids)) == len(ids), "rule ids must be unique"
    for r in rules:
        assert r["shortDescription"]["text"]
        assert r["fullDescription"]["text"]
        assert r["defaultConfiguration"]["level"] in {"none", "note", "warning", "error"}
        assert r["properties"]["tags"]


def test_result_rule_index_agrees_with_rules_array():
    """A wrong ruleIndex is silently accepted by some consumers and corrupts others."""
    report = _report(vulnerabilities=[_vuln()], guardrails=GuardrailAudit(score=0.1, missing=[MissingGuardrail(kind="scope", severity="high", suggested_text="Stay on topic.")]))
    doc = S.report_to_sarif(report, target_path="p.yaml")
    rules = doc["runs"][0]["tool"]["driver"]["rules"]
    for result in doc["runs"][0]["results"]:
        assert rules[result["ruleIndex"]]["id"] == result["ruleId"]


# --- severity mapping -------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "level"),
    [("info", "note"), ("low", "note"), ("medium", "warning"), ("high", "error"), ("critical", "error")],
)
def test_severity_maps_to_sarif_level(severity, level):
    report = _report(vulnerabilities=[_vuln(severity=severity)])
    results = S.report_results(report, target_path="p.yaml")
    assert results[0]["level"] == level
    assert results[0]["properties"]["spyvSeverity"] == severity


# --- single-prompt results --------------------------------------------------


def test_vulnerability_carries_owasp_tag_and_fix():
    report = _report(vulnerabilities=[_vuln()])
    r = S.report_results(report, target_path="prompt.yaml")[0]
    assert r["ruleId"] == "spyv/vulnerability"
    assert r["properties"]["owaspLlmTag"] == "LLM01"
    assert "Fix:" in r["message"]["text"]


def test_quality_and_optimization_findings_become_results_with_lines():
    report = _report(
        quality=QualityReport(
            score=0.4,
            findings=[SpyvFinding(id="q1", pillar="quality", severity="low", title="Vague", description="Be specific.", line=7)],
        ),
        optimization=OptimizationReport(
            score=0.4,
            total_tokens=99,
            findings=[SpyvFinding(id="o1", pillar="optimization", severity="info", title="Redundant", description="Trim it.")],
        ),
    )
    results = S.report_results(report, target_path="prompt.yaml")
    by_rule = {r["ruleId"]: r for r in results}
    assert by_rule["spyv/quality"]["locations"][0]["physicalLocation"]["region"]["startLine"] == 7
    # no line -> no region, rather than an invalid startLine
    assert "region" not in by_rule["spyv/optimization"]["locations"][0]["physicalLocation"]


def test_missing_guardrail_becomes_a_result():
    report = _report(
        guardrails=GuardrailAudit(
            score=0.2,
            missing=[MissingGuardrail(kind="pii_redaction", severity="high", suggested_text="Never echo PII.")],
        )
    )
    results = S.report_results(report, target_path="prompt.yaml")
    assert results[0]["ruleId"] == "spyv/missing-guardrail"
    assert results[0]["properties"]["guardrailKind"] == "pii_redaction"


def test_clean_report_produces_no_results():
    assert S.report_results(_report(), target_path="prompt.yaml") == []


@pytest.mark.parametrize("line", [None, 0, -3])
def test_non_positive_line_omits_region(line):
    report = _report(
        quality=QualityReport(score=0.1, findings=[SpyvFinding(id="q1", pillar="quality", severity="low", title="t", description="d", line=line)])
    )
    loc = S.report_results(report, target_path="p.yaml")[0]["locations"][0]["physicalLocation"]
    assert "region" not in loc


# --- project scan -----------------------------------------------------------


def test_project_scan_reports_unsafe_and_skips_ship():
    report = _project([_pp(), _pp(file="/repo/ok.py", identifier="fine", overall_verdict="ship", max_severity="info", n_vulnerabilities=0)])
    results = S.project_results(report)
    assert len(results) == 1
    assert results[0]["properties"]["verdict"] == "unsafe"


def test_project_scan_includes_fix_first():
    report = _project([_pp(overall_verdict="fix_first", max_severity="medium")])
    results = S.project_results(report)
    assert len(results) == 1
    assert results[0]["level"] == "warning"


def test_project_paths_are_repo_relative():
    report = _project([_pp(file="/repo/app/agents.py")], root="/repo")
    uri = S.project_results(report)[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "app/agents.py"


def test_path_outside_root_falls_back_to_given_path():
    report = _project([_pp(file="elsewhere/agents.py")], root="/repo")
    uri = S.project_results(report)[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "elsewhere/agents.py"


def test_singular_vulnerability_wording():
    report = _project([_pp(n_vulnerabilities=1)])
    assert "1 vulnerability." in S.project_results(report)[0]["message"]["text"]


# --- fingerprints -----------------------------------------------------------


def test_fingerprints_are_stable_across_runs():
    a = S.report_results(_report(vulnerabilities=[_vuln()]), target_path="p.yaml")[0]
    b = S.report_results(_report(vulnerabilities=[_vuln()]), target_path="p.yaml")[0]
    assert a["partialFingerprints"] == b["partialFingerprints"]


def test_fingerprints_differ_for_different_findings():
    a = S.report_results(_report(vulnerabilities=[_vuln(id="v1")]), target_path="p.yaml")[0]
    b = S.report_results(_report(vulnerabilities=[_vuln(id="v2")]), target_path="p.yaml")[0]
    assert a["partialFingerprints"] != b["partialFingerprints"]


def test_sarif_fingerprints_collects_every_finding():
    report = _report(
        vulnerabilities=[_vuln(id="v1"), _vuln(id="v2")],
        guardrails=GuardrailAudit(score=0.1, missing=[MissingGuardrail(kind="scope", severity="high", suggested_text="x")]),
    )
    doc = S.report_to_sarif(report, target_path="p.yaml")
    assert len(S.sarif_fingerprints(doc)) == 3


def test_sarif_fingerprints_on_empty_document():
    assert S.sarif_fingerprints({}) == set()


# --- writing ----------------------------------------------------------------


def test_write_sarif_emits_valid_json_and_creates_parents(tmp_path):
    doc = S.project_report_to_sarif(_project([_pp()]), tool_version="0.3.1")
    out = tmp_path / "nested" / "spyv.sarif"
    S.write_sarif(doc, out)
    assert json.loads(out.read_text())["runs"][0]["tool"]["driver"]["version"] == "0.3.1"

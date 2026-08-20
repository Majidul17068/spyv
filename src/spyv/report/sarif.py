"""SARIF 2.1.0 export.

Turns a spyv report into Static Analysis Results Interchange Format so findings
land inline on pull requests via GitHub / GitLab code scanning.

The rule catalog is deliberately *bounded*: code-scanning platforms track alerts
by rule id, so a fixed set of rules keeps alert history stable across runs while
the specific finding travels in the result message. Stable dedup across commits
comes from ``partialFingerprints``, which is also what lets ``--baseline``
recognise a finding it has seen before.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..contracts import ProjectReport, Report

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
)
INFORMATION_URI = "https://github.com/Majidul17068/spyv"

SarifLevel = Literal["none", "note", "warning", "error"]

# spyv severity -> SARIF level. SARIF has four levels, so low/info collapse to note
# and high/critical both fail a run; the precise band survives in security-severity.
_LEVEL: dict[str, SarifLevel] = {
    "info": "note",
    "low": "note",
    "medium": "warning",
    "high": "error",
    "critical": "error",
}

# GitHub code scanning bands its own UI severity from security-severity (0.0-10.0).
_SECURITY_SEVERITY: dict[str, str] = {
    "info": "1.0",
    "low": "3.0",
    "medium": "5.5",
    "high": "8.0",
    "critical": "9.5",
}


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    name: str
    short: str
    full: str
    tags: tuple[str, ...]
    level: SarifLevel = "warning"


RULES: tuple[_Rule, ...] = (
    _Rule(
        "spyv/vulnerability",
        "PromptVulnerability",
        "Prompt is vulnerable to attack",
        "The prompt permits an attack such as prompt injection, system-prompt "
        "disclosure, PII extraction, or excessive agency. Apply the suggested fix "
        "and re-run spyv to confirm the vulnerability no longer reproduces.",
        ("security", "external/cwe/cwe-1427", "owasp-llm"),
        "error",
    ),
    _Rule(
        "spyv/missing-guardrail",
        "MissingGuardrail",
        "Prompt is missing a guardrail",
        "The prompt does not state a constraint that its role and tools require, "
        "such as a scope limit, a refusal rule, or a confirmation step before a "
        "destructive action.",
        ("security", "guardrails"),
    ),
    _Rule(
        "spyv/secret-in-prompt",
        "SecretInPrompt",
        "Secret detected in prompt or output",
        "A credential-shaped string was matched by a deterministic checker, not an "
        "LLM judgement. Rotate the credential and load it from the environment "
        "instead of embedding it.",
        ("security", "external/cwe/cwe-798", "secrets"),
        "error",
    ),
    _Rule(
        "spyv/pii-in-prompt",
        "PiiInPrompt",
        "Personal data detected in prompt or output",
        "A deterministic checker matched personal data such as an email address, "
        "national identifier, phone number, or a Luhn-valid card number.",
        ("security", "external/cwe/cwe-359", "privacy"),
        "error",
    ),
    _Rule(
        "spyv/quality",
        "PromptQuality",
        "Prompt quality issue",
        "The prompt has a clarity, specificity, or structure problem that makes "
        "model behaviour less predictable.",
        ("quality", "maintainability"),
        "note",
    ),
    _Rule(
        "spyv/optimization",
        "PromptOptimization",
        "Prompt efficiency issue",
        "The prompt contains redundant or unnecessary tokens, increasing cost and "
        "latency on every call without changing behaviour.",
        ("performance", "cost"),
        "note",
    ),
    _Rule(
        "spyv/prompt-unsafe",
        "PromptAuditVerdict",
        "Prompt audit did not reach a shippable verdict",
        "A project scan audited this prompt and returned fix_first or unsafe. Run "
        "'spyv test' on the file for the full five-pillar report.",
        ("security", "audit"),
        "error",
    ),
)

_RULE_INDEX: dict[str, int] = {r.rule_id: i for i, r in enumerate(RULES)}

_PILLAR_RULE: dict[str, str] = {
    "quality": "spyv/quality",
    "optimization": "spyv/optimization",
    "vulnerability": "spyv/vulnerability",
    "guardrail": "spyv/missing-guardrail",
}


def _fingerprint(*parts: str) -> str:
    """Stable identity for a finding, so re-runs and baselines agree."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


def _uri(file: str, root: str | None = None) -> str:
    """SARIF wants a repo-relative, forward-slash URI."""
    p = Path(file)
    if root:
        try:
            p = p.resolve().relative_to(Path(root).resolve())
        except (ValueError, OSError):
            p = Path(file)
    return p.as_posix().lstrip("/")


def _location(uri: str, line: int | None) -> dict[str, Any]:
    physical: dict[str, Any] = {"artifactLocation": {"uri": uri}}
    # SARIF regions are 1-based; a 0 or None means "whole file", which we express
    # by omitting the region rather than emitting an invalid startLine.
    if line is not None and line > 0:
        physical["region"] = {"startLine": line}
    return {"physicalLocation": physical}


def _result(
    rule_id: str,
    severity: str,
    message: str,
    uri: str,
    line: int | None,
    fingerprint: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ruleId": rule_id,
        "ruleIndex": _RULE_INDEX[rule_id],
        "level": _LEVEL.get(severity, "warning"),
        "message": {"text": message},
        "locations": [_location(uri, line)],
        "partialFingerprints": {"spyvFindingId/v1": fingerprint},
        "properties": {"spyvSeverity": severity, **(properties or {})},
    }
    return result


def _driver(tool_version: str) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for r in RULES:
        rules.append(
            {
                "id": r.rule_id,
                "name": r.name,
                "shortDescription": {"text": r.short},
                "fullDescription": {"text": r.full},
                "defaultConfiguration": {"level": r.level},
                "helpUri": f"{INFORMATION_URI}#readme",
                "properties": {
                    "tags": list(r.tags),
                    "security-severity": _SECURITY_SEVERITY["high"],
                },
            }
        )
    return {
        "name": "spyv",
        "version": tool_version,
        "semanticVersion": tool_version,
        "informationUri": INFORMATION_URI,
        "rules": rules,
    }


def _envelope(tool_version: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": SARIF_VERSION,
        "$schema": SARIF_SCHEMA,
        "runs": [
            {
                "tool": {"driver": _driver(tool_version)},
                "results": results,
                "invocations": [{"executionSuccessful": True}],
                "columnKind": "utf16CodeUnits",
            }
        ],
    }


def report_results(report: Report, *, target_path: str, root: str | None = None) -> list[dict[str, Any]]:
    """SARIF results for a single-prompt ``spyv test`` report."""
    uri = _uri(target_path, root)
    results: list[dict[str, Any]] = []

    for v in report.vulnerabilities:
        props: dict[str, Any] = {"status": v.status, "category": v.category}
        if v.owasp_llm_tag:
            props["owaspLlmTag"] = v.owasp_llm_tag
        if v.mitre_atlas_id:
            props["mitreAtlasId"] = v.mitre_atlas_id
        detail = f"{v.title}. {v.description}".strip()
        if v.suggested_fix:
            detail = f"{detail} Fix: {v.suggested_fix}"
        results.append(
            _result(
                "spyv/vulnerability",
                v.severity,
                detail,
                uri,
                None,
                _fingerprint("vulnerability", v.id, v.category, report.target_hash),
                props,
            )
        )

    for finding in (*report.quality.findings, *report.optimization.findings):
        rule_id = _PILLAR_RULE.get(finding.pillar, "spyv/quality")
        props = {"pillar": finding.pillar}
        if finding.owasp_llm_tag:
            props["owaspLlmTag"] = finding.owasp_llm_tag
        detail = f"{finding.title}. {finding.description}".strip()
        results.append(
            _result(
                rule_id,
                finding.severity,
                detail,
                uri,
                finding.line,
                _fingerprint(rule_id, finding.id, finding.title, report.target_hash),
                props,
            )
        )

    for missing in report.guardrails.missing:
        results.append(
            _result(
                "spyv/missing-guardrail",
                missing.severity,
                f"Missing guardrail ({missing.kind}). Suggested: {missing.suggested_text}",
                uri,
                None,
                _fingerprint("missing-guardrail", missing.kind, report.target_hash),
                {"guardrailKind": missing.kind},
            )
        )

    return results


def report_to_sarif(
    report: Report, *, target_path: str, root: str | None = None, tool_version: str = "0.0.0"
) -> dict[str, Any]:
    """Full SARIF document for a single-prompt report."""
    return _envelope(tool_version, report_results(report, target_path=target_path, root=root))


def project_results(report: ProjectReport) -> list[dict[str, Any]]:
    """SARIF results for a project-wide ``spyv scan`` report."""
    results: list[dict[str, Any]] = []
    for r in report.results:
        if r.overall_verdict == "ship":
            continue
        uri = _uri(r.file, report.root)
        label = r.identifier or r.source_kind
        detail = (
            f"Prompt '{label}' scored {r.overall_score:.1f}/10 with verdict "
            f"{r.overall_verdict} and {r.n_vulnerabilities} vulnerability"
            f"{'' if r.n_vulnerabilities == 1 else 's'}."
        )
        if r.top_fix:
            detail = f"{detail} Top fix: {r.top_fix}"
        results.append(
            _result(
                "spyv/prompt-unsafe",
                r.max_severity,
                detail,
                uri,
                r.line,
                _fingerprint("prompt-unsafe", uri, r.identifier, r.source_kind),
                {
                    "verdict": r.overall_verdict,
                    "score": r.overall_score,
                    "sourceKind": r.source_kind,
                    "vulnerabilities": r.n_vulnerabilities,
                },
            )
        )
    return results


def project_report_to_sarif(report: ProjectReport, *, tool_version: str = "0.0.0") -> dict[str, Any]:
    """Full SARIF document for a project scan."""
    return _envelope(tool_version, project_results(report))


def write_sarif(document: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def sarif_fingerprints(document: dict[str, Any]) -> set[str]:
    """Every finding fingerprint in a SARIF document — the baseline's unit of identity."""
    out: set[str] = set()
    for run in document.get("runs", []):
        for result in run.get("results", []):
            fp = result.get("partialFingerprints", {}).get("spyvFindingId/v1")
            if fp:
                out.add(str(fp))
    return out


__all__ = [
    "RULES",
    "SARIF_SCHEMA",
    "SARIF_VERSION",
    "project_report_to_sarif",
    "project_results",
    "report_results",
    "report_to_sarif",
    "sarif_fingerprints",
    "write_sarif",
]

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .contracts import ProjectPromptResult, ProjectReport
from .discovery import discover
from .providers.base import LLMClient
from .reason import analyze

_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _max_severity(vulnerabilities: list) -> str:
    worst = "info"
    for v in vulnerabilities:
        if _SEVERITY_RANK.get(v.severity, 0) > _SEVERITY_RANK.get(worst, 0):
            worst = v.severity
    return worst


def scan(
    *,
    root: str | Path,
    llm: LLMClient,
    model: str,
    max_prompts: int = 25,
) -> ProjectReport:
    discovered, files_scanned = discover(root)
    total_found = len(discovered)
    truncated = total_found > max_prompts
    selected = discovered[:max_prompts]

    cache: dict[str, tuple] = {}
    results: list[ProjectPromptResult] = []
    ship = fix_first = unsafe = 0

    for d in selected:
        if d.system_prompt in cache:
            verdict, score, n_vulns, max_sev, top_fix = cache[d.system_prompt]
        else:
            report = analyze(
                system_prompt=d.system_prompt,
                llm=llm,
                model=model,
                tools=d.tools or None,
            )
            verdict = report.overall_verdict
            score = report.overall_score
            n_vulns = len(report.vulnerabilities)
            max_sev = _max_severity(report.vulnerabilities)
            top_fix = report.fixes[0].replacement if report.fixes else ""
            cache[d.system_prompt] = (verdict, score, n_vulns, max_sev, top_fix)

        if verdict == "ship":
            ship += 1
        elif verdict == "fix_first":
            fix_first += 1
        else:
            unsafe += 1

        results.append(
            ProjectPromptResult(
                file=d.file,
                line=d.line,
                source_kind=d.source_kind,
                identifier=d.identifier,
                overall_score=score,
                overall_verdict=verdict,
                n_vulnerabilities=n_vulns,
                max_severity=max_sev,  # type: ignore[arg-type]
                top_fix=top_fix,
            )
        )

    results.sort(key=lambda r: (r.overall_score, -_SEVERITY_RANK.get(r.max_severity, 0)))

    return ProjectReport(
        root=str(root),
        generated_at=datetime.now(timezone.utc).isoformat(),
        model_used=model,
        files_scanned=files_scanned,
        prompts_found=total_found,
        prompts_analyzed=len(results),
        truncated=truncated,
        ship=ship,
        fix_first=fix_first,
        unsafe=unsafe,
        results=results,
    )


__all__ = ["scan"]

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .contracts import DiscoveredPrompt, ProjectPromptResult, ProjectReport
from .discovery import discover
from .providers.base import LLMClient
from .reason import analyze

_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_DEFAULT_WORKERS = 8
_MAX_WORKERS = 32


def _max_severity(vulnerabilities: list) -> str:
    worst = "info"
    for v in vulnerabilities:
        if _SEVERITY_RANK.get(v.severity, 0) > _SEVERITY_RANK.get(worst, 0):
            worst = v.severity
    return worst


def _analyze_summary(
    d: DiscoveredPrompt,
    llm: LLMClient,
    model: str,
) -> tuple[str, float, int, str, str]:
    report = analyze(system_prompt=d.system_prompt, llm=llm, model=model, tools=d.tools or None)
    return (
        report.overall_verdict,
        report.overall_score,
        len(report.vulnerabilities),
        _max_severity(report.vulnerabilities),
        report.fixes[0].replacement if report.fixes else "",
    )


def scan(
    *,
    root: str | Path,
    llm: LLMClient,
    model: str,
    max_prompts: int = 25,
    max_workers: int = _DEFAULT_WORKERS,
) -> ProjectReport:
    discovered, files_scanned = discover(root)
    total_found = len(discovered)
    truncated = total_found > max_prompts
    selected = discovered[:max_prompts]

    unique: dict[str, DiscoveredPrompt] = {}
    for d in selected:
        unique.setdefault(d.system_prompt, d)

    analyzed: dict[str, tuple[str, float, int, str, str]] = {}
    if unique:
        workers = max(1, min(max_workers, _MAX_WORKERS, len(unique)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_analyze_summary, d, llm, model): key for key, d in unique.items()
            }
            for fut in futures:
                analyzed[futures[fut]] = fut.result()

    results: list[ProjectPromptResult] = []
    ship = fix_first = unsafe = 0
    for d in selected:
        verdict, score, n_vulns, max_sev, top_fix = analyzed[d.system_prompt]
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
                overall_verdict=verdict,  # type: ignore[arg-type]
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

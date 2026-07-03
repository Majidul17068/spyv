from __future__ import annotations

import os
import sys
from typing import IO

from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from spyv.contracts import ProjectReport, QueryProbeReport, Report

console: Console = Console(stderr=True)


_SEVERITY_STYLE: dict[str, str] = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "green",
    "info": "grey50",
}

_SEVERITY_RANK: dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

_VERDICT_STYLE: dict[str, str] = {
    "ship": "bold green",
    "fix_first": "bold yellow",
    "unsafe": "bold red",
}


def _sev_text(severity: str) -> Text:
    return Text(severity.upper(), style=_SEVERITY_STYLE.get(severity, "white"))


def _short_hash(h: str) -> str:
    return h[:12] if h else "unknown"


def _filter_by_level(severity: str, min_level: str) -> bool:
    return _SEVERITY_RANK.get(severity, 0) >= _SEVERITY_RANK.get(min_level, 0)


def _header(report: Report) -> Panel:
    verdict_style = _VERDICT_STYLE.get(report.overall_verdict, "white")
    line = Text()
    line.append("Spyv test", style="bold cyan")
    line.append(" - ")
    line.append(_short_hash(report.target_hash), style="magenta")
    line.append(" - model=")
    line.append(report.model_used, style="bold")
    line.append(" - verdict=")
    line.append(report.overall_verdict, style=verdict_style)
    return Panel(line, border_style="cyan", expand=True)


def _quality_panel(report: Report, min_level: str) -> Panel:
    q = report.quality
    header = Text()
    header.append("Score: ", style="bold")
    header.append(f"{q.score:.1f}/10", style="bold cyan")

    findings_table = Table(show_header=True, header_style="bold", expand=True)
    findings_table.add_column("Severity", no_wrap=True)
    findings_table.add_column("Line", justify="right", no_wrap=True)
    findings_table.add_column("Title")
    shown = [f for f in q.findings if _filter_by_level(f.severity, min_level)]
    if shown:
        for f in shown:
            findings_table.add_row(
                _sev_text(f.severity),
                str(f.line) if f.line is not None else "-",
                f.title,
            )
    else:
        findings_table.add_row(Text("-", style="grey50"), "-", Text("no findings", style="grey50"))

    strengths_group: list[Text] = []
    if q.strengths:
        strengths_group.append(Text("Strengths:", style="bold green"))
        for s in q.strengths:
            b = Text()
            b.append("  • ", style="green")
            b.append(s)
            strengths_group.append(b)
    else:
        strengths_group.append(Text("Strengths: none listed", style="grey50"))

    body = Group(header, Text(""), findings_table, Text(""), *strengths_group)
    return Panel(body, title="[bold]Quality[/bold]", border_style="blue", expand=True)


def _optimization_panel(report: Report, min_level: str) -> Panel:
    o = report.optimization
    stats = Table.grid(padding=(0, 2))
    stats.add_column(style="bold")
    stats.add_column()
    stats.add_row("Score", f"{o.score:.1f}/10")
    stats.add_row("Total tokens", str(o.total_tokens))
    stats.add_row("Redundant tokens", str(o.redundant_tokens))
    stats.add_row("Estimated savings (tokens)", str(o.estimated_savings_tokens))
    stats.add_row(
        "Estimated cost savings",
        f"${o.estimated_cost_savings_per_1k_calls_usd:.4f} / 1k calls",
    )
    stats.add_row(
        "Estimated latency reduction",
        f"{o.estimated_latency_reduction_ms:.1f} ms",
    )

    findings_table = Table(show_header=True, header_style="bold", expand=True)
    findings_table.add_column("Severity", no_wrap=True)
    findings_table.add_column("Line", justify="right", no_wrap=True)
    findings_table.add_column("Title")
    shown = [f for f in o.findings if _filter_by_level(f.severity, min_level)]
    if shown:
        for f in shown:
            findings_table.add_row(
                _sev_text(f.severity),
                str(f.line) if f.line is not None else "-",
                f.title,
            )
    else:
        findings_table.add_row(Text("-", style="grey50"), "-", Text("no findings", style="grey50"))

    body = Group(stats, Text(""), findings_table)
    return Panel(body, title="[bold]Optimization[/bold]", border_style="magenta", expand=True)


def _vulnerabilities_panel(report: Report, min_level: str) -> Panel:
    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("OWASP", no_wrap=True)
    table.add_column("Title")
    table.add_column("Root cause")

    shown = [v for v in report.vulnerabilities if _filter_by_level(v.severity, min_level)]
    if shown:
        for v in shown:
            table.add_row(
                _sev_text(v.severity),
                v.owasp_llm_tag or "-",
                v.title,
                v.root_cause or "-",
            )
    else:
        table.add_row(
            Text("-", style="grey50"),
            "-",
            Text("no vulnerabilities predicted", style="grey50"),
            "-",
        )

    return Panel(table, title="[bold]Vulnerabilities[/bold]", border_style="red", expand=True)


def _guardrails_panel(report: Report) -> Panel:
    g = report.guardrails

    found_table = Table(show_header=True, header_style="bold green", expand=True)
    found_table.add_column("Line", justify="right", no_wrap=True)
    found_table.add_column("Kind", no_wrap=True)
    found_table.add_column("Strength", no_wrap=True)
    found_table.add_column("Text")
    found_table.add_column("Bypass risk")
    if g.found:
        for gr in g.found:
            strength_style = {
                "strong": "green",
                "medium": "yellow",
                "weak": "red",
            }.get(gr.strength, "white")
            found_table.add_row(
                str(gr.line) if gr.line is not None else "-",
                gr.kind,
                Text(gr.strength, style=strength_style),
                gr.text,
                gr.bypass_risk or "-",
            )
    else:
        found_table.add_row("-", "-", "-", Text("no guardrails found", style="grey50"), "-")

    missing_table = Table(show_header=True, header_style="bold red", expand=True)
    missing_table.add_column("Severity", no_wrap=True)
    missing_table.add_column("Kind", no_wrap=True)
    missing_table.add_column("Suggested text")
    if g.missing:
        for m in g.missing:
            missing_table.add_row(_sev_text(m.severity), m.kind, m.suggested_text)
    else:
        missing_table.add_row("-", "-", Text("nothing missing", style="grey50"))

    header = Text()
    header.append("Score: ", style="bold")
    header.append(f"{g.score:.1f}/10", style="bold cyan")

    body = Group(
        header,
        Text(""),
        Text("Found:", style="bold green"),
        found_table,
        Text(""),
        Text("Missing:", style="bold red"),
        missing_table,
    )
    return Panel(body, title="[bold]Guardrails[/bold]", border_style="yellow", expand=True)


def _fixes_panel(report: Report) -> Panel:
    if not report.fixes:
        return Panel(
            Text("no fixes suggested", style="grey50"),
            title="[bold]Fixes[/bold]",
            border_style="green",
            expand=True,
        )

    ordered = sorted(report.fixes, key=lambda f: f.priority)
    blocks: list[Text | Panel] = []
    for idx, fix in enumerate(ordered, start=1):
        header = Text()
        header.append(f"{idx}. ", style="bold cyan")
        header.append(f"[{fix.kind}] ", style="bold magenta")
        header.append(fix.insertion_point or "(no insertion point)", style="bold")
        header.append(f"  priority={fix.priority}", style="grey50")

        replacement_panel = Panel(
            Text(fix.replacement, style="white on grey11"),
            border_style="grey37",
            title="replacement",
            title_align="left",
            expand=True,
        )

        rationale = Text()
        rationale.append("Rationale: ", style="bold")
        rationale.append(fix.rationale)

        addresses = Text()
        addresses.append("Addresses: ", style="bold")
        if fix.addresses:
            addresses.append(", ".join(fix.addresses), style="cyan")
        else:
            addresses.append("-", style="grey50")

        blocks.append(header)
        blocks.append(replacement_panel)
        blocks.append(rationale)
        blocks.append(addresses)
        blocks.append(Text(""))

    return Panel(Group(*blocks), title="[bold]Fixes[/bold]", border_style="green", expand=True)


def _footer(report: Report) -> Panel:
    n_findings = (
        len(report.quality.findings)
        + len(report.optimization.findings)
        + len(report.vulnerabilities)
    )
    n_fixes = len(report.fixes)
    verdict_style = _VERDICT_STYLE.get(report.overall_verdict, "white")

    line = Text()
    line.append("verdict=", style="bold")
    line.append(report.overall_verdict, style=verdict_style)
    line.append("  overall_score=", style="bold")
    line.append(f"{report.overall_score:.1f}/10", style="bold cyan")
    line.append(f"  {n_findings} findings", style="white")
    line.append(f"  {n_fixes} fixes", style="white")
    return Panel(line, border_style="cyan", expand=True)


def _resolve_console(color: bool | None) -> Console:
    if color is None:
        return console
    return Console(stderr=True, force_terminal=color, no_color=not color)


def render_report(report: Report, *, color: bool | None = None) -> None:
    out_mode = os.environ.get("SPYV_OUT", "").lower() or "auto"
    json_path = os.environ.get("SPYV_JSON_PATH")
    min_level = os.environ.get("SPYV_LEVEL", "info").lower()
    if min_level not in _SEVERITY_RANK:
        min_level = "info"

    if out_mode == "json":
        emit_json(report)
        return

    target_console = _resolve_console(color)
    target_console.print(_header(report))
    target_console.print(_quality_panel(report, min_level))
    target_console.print(_optimization_panel(report, min_level))
    target_console.print(_vulnerabilities_panel(report, min_level))
    target_console.print(_guardrails_panel(report))
    target_console.print(_fixes_panel(report))
    target_console.print(_footer(report))

    if out_mode == "both":
        if json_path:
            with open(json_path, "w", encoding="utf-8") as fh:
                emit_json(report, fh)
        else:
            emit_json(report)


def render_progress(steps: list[str]) -> Progress:
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    for step in steps:
        progress.add_task(step, total=1)
    return progress


def emit_json(report: Report, stream: IO[str] | None = None) -> None:
    target = stream if stream is not None else sys.stdout
    target.write(report.model_dump_json())
    target.write("\n")
    target.flush()


_VERDICT_STYLE = {
    "safe": "green",
    "off_scope": "yellow",
    "leaked": "bold red",
    "complied_with_attack": "bold red",
    "error": "grey50",
    "ship": "green",
    "fix_first": "yellow",
    "unsafe": "bold red",
}


def render_probe_report(report: QueryProbeReport, *, color: bool | None = None) -> None:
    con = _resolve_console(color)
    header = Text()
    header.append("Spyv probe", style="bold cyan")
    header.append(f"  {_short_hash(report.target_hash)}")
    header.append(f"  model={report.model_used}")
    header.append(f"  score={report.score:.1f}/10", style="bold")
    header.append(f"  {report.passed}/{report.total} passed")
    con.print(Panel(header, border_style="cyan"))

    for i, r in enumerate(report.results, 1):
        vstyle = _VERDICT_STYLE.get(r.verdict, "white")
        body = Text()
        body.append(f"query: {r.query}\n", style="bold")
        body.append(f"verdict: {r.verdict}", style=vstyle)
        body.append(f"   severity: {r.severity}", style=_SEVERITY_STYLE.get(r.severity, "white"))
        body.append(f"   guardrail_held: {r.guardrail_held}   on_scope: {r.on_scope}\n")
        response_preview = r.agent_response if len(r.agent_response) <= 240 else r.agent_response[:240] + "…"
        body.append(f"response: {response_preview}\n", style="grey70")
        if r.weakest_point:
            body.append(f"weakest point: {r.weakest_point}\n", style="yellow")
        if r.suggested_fix:
            body.append("fix: ", style="bold green")
            body.append(r.suggested_fix)
        title = f"[{i}] {'PASS' if (r.verdict == 'safe' and r.guardrail_held) else 'FAIL'}"
        con.print(Panel(body, title=title, border_style=vstyle))


def emit_probe_json(report: QueryProbeReport, stream: IO[str] | None = None) -> None:
    target = stream if stream is not None else sys.stdout
    target.write(report.model_dump_json())
    target.write("\n")
    target.flush()


def render_project_report(report: ProjectReport, *, color: bool | None = None) -> None:
    con = _resolve_console(color)
    header = Text()
    header.append("Spyv scan", style="bold cyan")
    header.append(f"  {report.root}")
    header.append(f"  ·  {report.files_scanned} files")
    header.append(f"  ·  {report.prompts_found} prompts")
    header.append(f"  ·  model={report.model_used}")
    con.print(Panel(header, border_style="cyan"))

    summary = Text()
    summary.append(f"  ship: {report.ship}", style="green")
    summary.append(f"    fix_first: {report.fix_first}", style="yellow")
    summary.append(f"    unsafe: {report.unsafe}", style="bold red")
    if report.truncated:
        summary.append(f"   (showing first {report.prompts_analyzed} of {report.prompts_found})", style="grey50")
    con.print(summary)

    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Verdict", no_wrap=True)
    table.add_column("Score", justify="right", no_wrap=True)
    table.add_column("Sev", no_wrap=True)
    table.add_column("Prompt", no_wrap=True)
    table.add_column("Location")
    for r in report.results:
        vstyle = _VERDICT_STYLE.get(r.overall_verdict, "white")
        loc = r.file
        if r.line is not None:
            loc = f"{loc}:{r.line}"
        table.add_row(
            Text(r.overall_verdict, style=vstyle),
            f"{r.overall_score:.1f}",
            Text(r.max_severity, style=_SEVERITY_STYLE.get(r.max_severity, "white")),
            r.identifier or "-",
            loc,
        )
    con.print(table)


def emit_project_json(report: ProjectReport, stream: IO[str] | None = None) -> None:
    target = stream if stream is not None else sys.stdout
    target.write(report.model_dump_json())
    target.write("\n")
    target.flush()


def format_summary(report: Report) -> str:
    n_findings = (
        len(report.quality.findings)
        + len(report.optimization.findings)
        + len(report.vulnerabilities)
    )
    n_fixes = len(report.fixes)
    return (
        f"spyv[{_short_hash(report.target_hash)}] "
        f"model={report.model_used} "
        f"verdict={report.overall_verdict} "
        f"score={report.overall_score:.1f}/10 "
        f"findings={n_findings} fixes={n_fixes}"
    )


__all__ = [
    "console",
    "emit_json",
    "emit_probe_json",
    "format_summary",
    "render_probe_report",
    "render_progress",
    "render_report",
]

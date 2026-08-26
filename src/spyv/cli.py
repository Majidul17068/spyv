from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from spyv import __version__, terminal
from spyv import reason as reason_module
from spyv.contracts import Report

VERSION = __version__ if isinstance(__version__, str) else "0.0.1"
AUP_PATH = Path.home() / ".spyv" / "accepted-aup-v1"
POLICY_CANDIDATES = [
    Path(__file__).resolve().parent.parent.parent / "POLICY.md",
    Path(__file__).resolve().parent.parent.parent.parent / "POLICY.md",
    Path.cwd() / "POLICY.md",
]


def _find_policy_file() -> Path | None:
    for candidate in POLICY_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _load_target(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            click.echo("Error: 'pyyaml' is required to read YAML files.", err=True)
            sys.exit(2)
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            click.echo(f"Error: failed to parse YAML: {exc}", err=True)
            sys.exit(2)
        if not isinstance(data, dict):
            click.echo("Error: YAML root must be a mapping.", err=True)
            sys.exit(2)
        return {
            "system_prompt": data.get("system_prompt", ""),
            "tools": data.get("tools", []) or [],
            "retrieval_sources": data.get("retrieval_sources", []) or [],
            "nshot_examples": data.get("nshot_examples", []) or [],
            "raw": data,
        }
    return {
        "system_prompt": text,
        "tools": [],
        "retrieval_sources": [],
        "nshot_examples": [],
        "raw": text,
    }


_SEVERITY_EXIT = {"info": 0, "low": 0, "medium": 1, "high": 2, "critical": 3}

# Ordering used by --fail-on. Kept separate from _SEVERITY_EXIT, which maps a
# severity to a legacy process exit code rather than to a rank.
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

GATE_CHOICES = ("none", "low", "medium", "high", "critical")

# Exit code used when a severity gate trips. Distinct from 2, which means the
# run itself failed (bad target, provider error), so CI can tell a real finding
# from a broken invocation.
GATE_EXIT = 1


def _worst(severities: list[str]) -> str:
    if not severities:
        return "info"
    return max(severities, key=lambda s: _SEVERITY_RANK.get(s, 0))


def _report_max_severity(report: Report) -> str:
    return _worst(
        [f.severity for f in report.quality.findings]
        + [f.severity for f in report.optimization.findings]
        + [v.severity for v in report.vulnerabilities]
        + [m.severity for m in report.guardrails.missing]
    )


def _gate_tripped(max_severity: str, fail_on: str | None) -> bool:
    if not fail_on or fail_on == "none":
        return False
    return _SEVERITY_RANK.get(max_severity, 0) >= _SEVERITY_RANK.get(fail_on, 99)


def _emit_sarif(document: dict[str, Any], out: Path) -> None:
    from spyv.report.sarif import write_sarif

    try:
        write_sarif(document, out)
    except OSError as exc:
        click.echo(f"Error writing --sarif: {exc}", err=True)
        sys.exit(2)



def _exit_code_for(report: Report) -> int:
    max_sev = 0
    for f in report.quality.findings:
        max_sev = max(max_sev, _SEVERITY_EXIT.get(f.severity, 0))
    for f in report.optimization.findings:
        max_sev = max(max_sev, _SEVERITY_EXIT.get(f.severity, 0))
    for v in report.vulnerabilities:
        max_sev = max(max_sev, _SEVERITY_EXIT.get(v.severity, 0))
    for m in report.guardrails.missing:
        max_sev = max(max_sev, _SEVERITY_EXIT.get(m.severity, 0))
    if report.overall_verdict == "unsafe":
        max_sev = max(max_sev, 3)
    elif report.overall_verdict == "fix_first":
        max_sev = max(max_sev, 1)
    return max_sev


def _emit_json(report: Report) -> None:
    click.echo(report.model_dump_json(indent=2))


def _write_out(report: Report, path: Path, fmt: str) -> None:
    if fmt == "json":
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    elif fmt == "md":
        path.write_text(terminal.render_markdown(report), encoding="utf-8")
    else:
        path.write_text(terminal.render_text(report), encoding="utf-8")


@click.group(invoke_without_command=True)
@click.version_option(VERSION, "--version", prog_name="spyv")
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command("init")
@click.option("--consent", is_flag=True, help="Skip interactive prompt (for CI).")
def init_cmd(consent: bool) -> None:
    policy_path = _find_policy_file()
    if policy_path is not None:
        try:
            click.echo(policy_path.read_text(encoding="utf-8"))
        except OSError as exc:
            click.echo(f"Error reading POLICY.md: {exc}", err=True)
            sys.exit(2)
    else:
        click.echo("POLICY.md not found; please review the Acceptable Use Policy.")

    if not consent:
        try:
            answer = click.prompt(
                "Do you accept the Acceptable Use Policy? [y/N]",
                default="N",
                show_default=False,
            )
        except (KeyboardInterrupt, click.Abort):
            click.echo("\nAborted.", err=True)
            sys.exit(130)
        if answer.strip().lower() not in ("y", "yes"):
            click.echo("Acceptance declined. Exiting.", err=True)
            sys.exit(1)

    AUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    stamp = datetime.now(timezone.utc).isoformat()
    AUP_PATH.write_text(f"{stamp}\t{user}\n", encoding="utf-8")
    click.echo(f"Recorded acceptance at {AUP_PATH}")


@main.command("test")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--model", "model", required=True, help="Model name (required).")
@click.option(
    "--provider",
    "provider_name",
    default="auto",
    help="LLM provider: auto, openai, anthropic, gemini, vllm, ollama, lmstudio, openai-compat.",
)
@click.option("--base-url", "base_url", default=None, help="Base URL for local / compatible endpoints.")
@click.option("--attack", is_flag=True, help="Enable attack mode (v0.1 preview).")
@click.option("--ci", "ci", is_flag=True, help="Non-interactive JSON output.")
@click.option("--json", "json_out", is_flag=True, help="Emit JSON to stdout.")
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=None)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "md", "json"]),
    default="text",
)
@click.option(
    "--sarif",
    "sarif_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write SARIF 2.1.0 to this path (for GitHub/GitLab code scanning).",
)
@click.option(
    "--fail-on",
    "fail_on",
    type=click.Choice(GATE_CHOICES),
    default=None,
    help="Exit 1 if any finding is at or above this severity. Use in CI.",
)
@click.option("--no-color", is_flag=True, help="Disable ANSI colors.")
def test_cmd(
    path: Path,
    model: str,
    provider_name: str,
    base_url: str | None,
    attack: bool,
    ci: bool,
    json_out: bool,
    out_path: Path | None,
    fmt: str,
    sarif_path: Path | None,
    fail_on: str | None,
    no_color: bool,
) -> None:
    if no_color:
        os.environ["NO_COLOR"] = "1"


    if not path.exists():
        click.echo(f"Error: file not found: {path}", err=True)
        sys.exit(2)

    try:
        target = _load_target(path)
    except FileNotFoundError:
        click.echo(f"Error: file not found: {path}", err=True)
        sys.exit(2)
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)

    from spyv.providers import auto as provider_auto
    from spyv.providers import provider as make_provider
    from spyv.providers.base import ProviderError

    try:
        if provider_name == "auto":
            client: Any = provider_auto(model=model)
        else:
            client = make_provider(provider_name, model=model, base_url=base_url)
    except ProviderError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

    try:
        report = reason_module.analyze(
            system_prompt=target["system_prompt"],
            llm=client,
            model=model,
            tools=target["tools"] or None,
            retrieval_sources=target["retrieval_sources"] or None,
            nshot_examples=target["nshot_examples"] or None,
        )
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

    if ci or json_out:
        _emit_json(report)
    else:
        terminal.render_report(report)

    if out_path is not None:
        try:
            _write_out(report, out_path, fmt)
        except OSError as exc:
            click.echo(f"Error writing --out: {exc}", err=True)
            sys.exit(2)

    exit_code = _exit_code_for(report)
    max_severity = _report_max_severity(report)

    if attack:
        from spyv.redteam import redteam as run_redteam

        if not (ci or json_out):
            click.echo("Firing the attack corpus ...", err=True)
        rt = run_redteam(
            system_prompt=target["system_prompt"],
            llm=client,
            model=model,
            tools=target["tools"] or None,
        )
        if ci or json_out:
            terminal.emit_redteam_json(rt)
        else:
            terminal.render_redteam_report(rt)
        if rt.breached and exit_code < 2:
            exit_code = 2
        if rt.breached:
            # A confirmed breach outranks anything the static audit predicted.
            max_severity = "critical"

    if sarif_path is not None:
        from spyv.report.sarif import report_to_sarif

        _emit_sarif(
            report_to_sarif(report, target_path=str(path), tool_version=VERSION), sarif_path
        )

    if fail_on is not None:
        sys.exit(GATE_EXIT if _gate_tripped(max_severity, fail_on) else 0)

    sys.exit(exit_code)


@main.command("probe")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--model", "model", required=True, help="Model name (required).")
@click.option("--provider", "provider_name", default="auto", help="LLM provider (default: auto).")
@click.option("--base-url", "base_url", default=None, help="Base URL for local / compatible endpoints.")
@click.option("--query", "queries", multiple=True, help="A user query to probe (repeatable).")
@click.option(
    "--queries-file",
    "queries_file",
    type=click.Path(path_type=Path),
    default=None,
    help="File with one query per line.",
)
@click.option("--ci", "ci", is_flag=True, help="Non-interactive JSON output.")
@click.option("--json", "json_out", is_flag=True, help="Emit JSON to stdout.")
@click.option("--no-color", is_flag=True, help="Disable ANSI colors.")
def probe_cmd(
    path: Path,
    model: str,
    provider_name: str,
    base_url: str | None,
    queries: tuple[str, ...],
    queries_file: Path | None,
    ci: bool,
    json_out: bool,
    no_color: bool,
) -> None:
    if no_color:
        os.environ["NO_COLOR"] = "1"

    if not path.exists():
        click.echo(f"Error: file not found: {path}", err=True)
        sys.exit(2)

    query_list = list(queries)
    if queries_file is not None:
        try:
            text = queries_file.read_text(encoding="utf-8")
        except OSError as exc:
            click.echo(f"Error reading --queries-file: {exc}", err=True)
            sys.exit(2)
        query_list.extend(line.strip() for line in text.splitlines() if line.strip())

    if not query_list:
        click.echo("Error: provide at least one --query or --queries-file.", err=True)
        sys.exit(2)

    target = _load_target(path)

    from spyv.probe import probe as run_probe
    from spyv.providers import auto as provider_auto
    from spyv.providers import provider as make_provider
    from spyv.providers.base import ProviderError

    try:
        if provider_name == "auto":
            client: Any = provider_auto(model=model)
        else:
            client = make_provider(provider_name, model=model, base_url=base_url)
    except ProviderError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

    try:
        report = run_probe(
            system_prompt=target["system_prompt"],
            queries=query_list,
            llm=client,
            model=model,
            tools=target["tools"] or None,
        )
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)

    if ci or json_out:
        terminal.emit_probe_json(report)
    else:
        terminal.render_probe_report(report)

    sys.exit(0 if report.failed == 0 else 2)


@main.command("scan")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--model", "model", required=True, help="Model name (required).")
@click.option("--provider", "provider_name", default="auto", help="LLM provider (default: auto).")
@click.option("--base-url", "base_url", default=None, help="Base URL for local / compatible endpoints.")
@click.option("--max-prompts", "max_prompts", default=25, help="Cap prompts analyzed (default: 25).")
@click.option("--concurrency", "concurrency", default=8, help="Prompts audited in parallel (default: 8).")
@click.option("--ci", "ci", is_flag=True, help="Non-interactive JSON output.")
@click.option("--json", "json_out", is_flag=True, help="Emit JSON to stdout.")
@click.option(
    "--sarif",
    "sarif_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write SARIF 2.1.0 to this path (for GitHub/GitLab code scanning).",
)
@click.option(
    "--fail-on",
    "fail_on",
    type=click.Choice(GATE_CHOICES),
    default=None,
    help="Exit 1 if any prompt has a finding at or above this severity.",
)
@click.option("--no-color", is_flag=True, help="Disable ANSI colors.")
def scan_cmd(
    path: Path,
    model: str,
    provider_name: str,
    base_url: str | None,
    max_prompts: int,
    concurrency: int,
    ci: bool,
    json_out: bool,
    sarif_path: Path | None,
    fail_on: str | None,
    no_color: bool,
) -> None:
    if no_color:
        os.environ["NO_COLOR"] = "1"
    if not path.exists():
        click.echo(f"Error: path not found: {path}", err=True)
        sys.exit(2)

    from spyv.providers import auto as provider_auto
    from spyv.providers import provider as make_provider
    from spyv.providers.base import ProviderError
    from spyv.scan import scan as run_scan

    try:
        if provider_name == "auto":
            client: Any = provider_auto(model=model)
        else:
            client = make_provider(provider_name, model=model, base_url=base_url)
    except ProviderError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

    if not (ci or json_out):
        click.echo(f"Discovering and auditing prompts under {path} ...", err=True)

    try:
        report = run_scan(
            root=path, llm=client, model=model, max_prompts=max_prompts, max_workers=concurrency
        )
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)

    if ci or json_out:
        terminal.emit_project_json(report)
    else:
        terminal.render_project_report(report)

    if sarif_path is not None:
        from spyv.report.sarif import project_report_to_sarif

        _emit_sarif(project_report_to_sarif(report, tool_version=VERSION), sarif_path)

    if fail_on is not None:
        # Gated on the same prompts SARIF reports, so a tripped gate always has
        # a corresponding alert. Prompts that reached 'ship' are excluded.
        worst = _worst([r.max_severity for r in report.results if r.overall_verdict != "ship"])
        sys.exit(GATE_EXIT if _gate_tripped(worst, fail_on) else 0)

    sys.exit(0 if report.unsafe == 0 else 2)


@main.command("redteam")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--model", "model", required=True, help="Model name (required).")
@click.option("--provider", "provider_name", default="auto", help="LLM provider (default: auto).")
@click.option("--base-url", "base_url", default=None, help="Base URL for local / compatible endpoints.")
@click.option("--category", "categories", multiple=True, help="Limit to OWASP categories, e.g. LLM01 (repeatable).")
@click.option("--ci", "ci", is_flag=True, help="Non-interactive JSON output.")
@click.option("--json", "json_out", is_flag=True, help="Emit JSON to stdout.")
@click.option("--no-color", is_flag=True, help="Disable ANSI colors.")
def redteam_cmd(
    path: Path,
    model: str,
    provider_name: str,
    base_url: str | None,
    categories: tuple[str, ...],
    ci: bool,
    json_out: bool,
    no_color: bool,
) -> None:
    if no_color:
        os.environ["NO_COLOR"] = "1"
    if not path.exists():
        click.echo(f"Error: file not found: {path}", err=True)
        sys.exit(2)

    target = _load_target(path)

    from spyv.providers import auto as provider_auto
    from spyv.providers import provider as make_provider
    from spyv.providers.base import ProviderError
    from spyv.redteam import redteam as run_redteam

    try:
        if provider_name == "auto":
            client: Any = provider_auto(model=model)
        else:
            client = make_provider(provider_name, model=model, base_url=base_url)
    except ProviderError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

    if not (ci or json_out):
        click.echo(f"Firing attacks at {path} ...", err=True)

    try:
        report = run_redteam(
            system_prompt=target["system_prompt"],
            llm=client,
            model=model,
            categories=list(categories) or None,
            tools=target["tools"] or None,
        )
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)

    if ci or json_out:
        terminal.emit_redteam_json(report)
    else:
        terminal.render_redteam_report(report)

    sys.exit(0 if report.breached == 0 else 2)


@main.command("exec")
@click.argument("cmd", nargs=-1)
def exec_cmd(cmd: tuple[str, ...]) -> None:
    click.echo("runtime observation ships in v0.5")
    sys.exit(3)


@main.command("verify")
@click.argument("run_id", required=False)
def verify_cmd(run_id: str | None) -> None:
    click.echo("verify ships in v0.5")
    sys.exit(3)


@main.command("bench")
@click.option("--dataset", "dataset", type=click.Path(path_type=Path), default=None,
              help="Labeled dataset YAML (default: bundled seed set).")
@click.option("--tier", type=click.Choice(["deterministic", "llm", "all"]), default="deterministic",
              help="deterministic (no key) | llm | all (adds redteam).")
@click.option("--provider", "provider_name", default="auto", help="LLM provider (default: auto).")
@click.option("--model", "model", default=None, help="Model name (needed for llm/all tiers).")
@click.option("--base-url", "base_url", default=None, help="Base URL for local/compatible endpoints.")
@click.option("--repeat", "repeat", default=1, help="Repeat each case K times (consistency).")
@click.option("--json", "json_out", is_flag=True, help="Emit JSON instead of the pretty report.")
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=None,
              help="Write full JSON results to this path.")
def bench_cmd(
    dataset: Path | None,
    tier: str,
    provider_name: str,
    model: str | None,
    base_url: str | None,
    repeat: int,
    json_out: bool,
    out_path: Path | None,
) -> None:
    """Measure spyv against a labeled dataset.

    Deterministic and LLM-judge accuracy are reported SEPARATELY. The
    deterministic tier needs no API key and is fully reproducible. Exit code is
    non-zero if a known deterministic-detectable case is missed (CI regression
    guard).
    """
    import json as _json

    from spyv.bench import format_report, run_benchmark
    from spyv.providers.base import ProviderError

    try:
        results = run_benchmark(
            dataset_path=dataset,
            tier=tier,
            provider_name=provider_name,
            model=model,
            base_url=base_url,
            repeat=repeat,
            out=out_path,
        )
    except ProviderError as exc:
        click.echo(f"Provider error: {exc}", err=True)
        sys.exit(2)
    except Exception as exc:
        click.echo(f"Benchmark error: {exc}", err=True)
        sys.exit(2)

    if json_out:
        click.echo(_json.dumps(results, indent=2))
    else:
        click.echo(format_report(results))

    det = results["tiers"]["deterministic"]["metrics"]
    sys.exit(1 if det["fn"] > 0 else 0)


@main.command("corpus")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option("--name", "names", multiple=True, help="Label for each path, in order (repeatable).")
@click.option("--json", "json_out", is_flag=True, help="Emit JSON instead of the pretty report.")
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=None, help="Write full JSON results here.")
@click.option(
    "--reveal",
    is_flag=True,
    help="Do NOT redact matched evidence. Requires --out; never prints secrets to stdout.",
)
@click.option(
    "--fail-on-exposure",
    is_flag=True,
    help="Exit 1 if any real prompt contains a secret or personal data.",
)
def corpus_cmd(
    paths: tuple[Path, ...],
    names: tuple[str, ...],
    json_out: bool,
    out_path: Path | None,
    reveal: bool,
    fail_on_exposure: bool,
) -> None:
    """Benchmark discovery and the deterministic checkers against real repositories.

    Needs no API key and calls no model, so results are reproducible. Measures
    discovery yield by construct, agreement with a naive grep baseline, and
    credentials or personal data sitting in prompts that are already committed.

    Matched evidence is redacted unless --reveal is passed, and --reveal refuses
    to print to stdout: a credential in a public repository is still live.
    """
    import json as _json

    from spyv.bench import format_corpus_report, run_corpus

    if reveal and out_path is None:
        click.echo("Error: --reveal requires --out (evidence is never printed to stdout).", err=True)
        sys.exit(2)

    results = run_corpus(list(paths), names=list(names) or None, reveal=reveal)

    if out_path is not None:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(_json.dumps(results, indent=2), encoding="utf-8")
        except OSError as exc:
            click.echo(f"Error writing --out: {exc}", err=True)
            sys.exit(2)

    if json_out:
        # Redact the stdout copy even when --out holds the unredacted findings.
        safe = {**results, "repos": [{**r, "findings": []} for r in results["repos"]]} if reveal else results
        click.echo(_json.dumps(safe, indent=2))
    else:
        click.echo(format_corpus_report(results))

    if fail_on_exposure and results["totals"]["exposure"]["prompts_with_hits"] > 0:
        sys.exit(GATE_EXIT)
    sys.exit(0)


@main.command("annotate")
@click.option("--sample", "sample_n", type=int, default=None,
              help="Draw a new stratified sample of N sites.")
@click.option("--resume", "resume_path", type=click.Path(path_type=Path), default=None,
              help="Continue labelling an existing file.")
@click.option("--score", "score_path", type=click.Path(path_type=Path), default=None,
              help="Report precision and agreement.")
@click.option("--second", "second_path", type=click.Path(path_type=Path), default=None,
              help="A second independent labelling pass, for agreement.")
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=Path("labels.json"))
def annotate_cmd(
    sample_n: int | None,
    resume_path: Path | None,
    score_path: Path | None,
    second_path: Path | None,
    out_path: Path,
) -> None:
    """Label a sample of prompt sites by hand, to measure detector precision.

    The visibility metric's denominator is whatever the detectors enumerate, so
    every figure derived from it inherits their precision -- and nothing in the
    pipeline checks it. This does.

    Write your labelling rules down before you start. A documented rule applied
    consistently is defensible; a judgement call remembered afterwards is not.
    """
    import json as _json

    from spyv.bench.annotate import attach_snippets, draw_sample, load, save, score

    if score_path is not None:
        items, _meta = load(score_path)
        second = load(second_path)[0] if second_path else None
        click.echo(_json.dumps(score(items, second), indent=2))
        return

    if resume_path is not None:
        items, meta = load(resume_path)
        out_path = resume_path
    elif sample_n is not None:
        click.echo(f"Drawing a stratified sample of {sample_n} sites ...", err=True)
        items = draw_sample(sample_n)
        if not items:
            click.echo("No sites found. Fetch the corpus first.", err=True)
            sys.exit(2)
        attach_snippets(items)
        meta = {"sample_size": len(items)}
        save(items, out_path, meta)
    else:
        click.echo("Give --sample N to start, --resume FILE to continue, or --score FILE.", err=True)
        sys.exit(2)

    todo = [i for i in items if not i.labelled]
    click.echo(f"\n{len(items) - len(todo)}/{len(items)} already labelled. "
               f"Ctrl-C saves and exits.\n", err=True)

    try:
        for idx, item in enumerate(todo, 1):
            click.echo("=" * 72)
            click.echo(f"[{idx}/{len(todo)}]  {item.repo}/{item.file}:{item.line}")
            click.echo(f"construct: {item.construct}   detector says: {item.predicted_visibility}")
            if item.predicted_text:
                click.echo(f"recovered: {item.predicted_text[:200]!r}")
            click.echo("-" * 72)
            click.echo(item.snippet or "(source unavailable)")
            click.echo("-" * 72)

            ans = click.prompt("Is this a prompt site? [y]es / [n]o / [s]kip", default="y")
            if ans.lower().startswith("s"):
                continue
            item.is_prompt_site = ans.lower().startswith("y")
            if item.is_prompt_site:
                item.true_visibility = click.prompt(
                    "Visibility: [1] static  [2] partial  [3] opaque",
                    type=click.Choice(["1", "2", "3"]), show_choices=False,
                    default={"static": "1", "partial": "2", "opaque": "3"}[item.predicted_visibility],
                )
                item.true_visibility = {"1": "static", "2": "partial", "3": "opaque"}[item.true_visibility]
            item.note = click.prompt("note (optional)", default="", show_default=False)
            save(items, out_path, meta)
    except (KeyboardInterrupt, click.Abort):
        click.echo("\nSaved.", err=True)

    save(items, out_path, meta)
    done = sum(1 for i in items if i.labelled)
    click.echo(f"\n{done}/{len(items)} labelled -> {out_path}", err=True)
    click.echo(f"Score it with:  spyv annotate --score {out_path}", err=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)

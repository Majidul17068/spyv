from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from spyv import __version__
from spyv import reason as reason_module
from spyv import terminal
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
    no_color: bool,
) -> None:
    if no_color:
        os.environ["NO_COLOR"] = "1"

    if attack:
        click.echo(
            "Note: --attack ships fully in v0.1; running static reasoning only.",
            err=True,
        )

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

    sys.exit(_exit_code_for(report))


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


@main.command("redteam")
@click.argument("path", type=click.Path(path_type=Path), required=False)
def redteam_cmd(path: Path | None) -> None:
    click.echo("red-team ships in v0.1")
    sys.exit(3)


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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)

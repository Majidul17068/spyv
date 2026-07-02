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


class OpenAIAdapter:
    def __init__(self) -> None:
        try:
            import openai
        except ImportError:
            click.echo(
                "Error: 'openai' package is not installed. Install with: pip install openai",
                err=True,
            )
            sys.exit(2)
        if not os.environ.get("OPENAI_API_KEY"):
            click.echo(
                "Error: OPENAI_API_KEY environment variable is not set.",
                err=True,
            )
            sys.exit(2)
        self._client = openai.OpenAI()

    def chat_completion(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.0,
    ) -> str:
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        content = response.choices[0].message.content
        return content or ""


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

    if os.environ.get("OPENAI_API_KEY"):
        client: Any = OpenAIAdapter()
    else:
        click.echo(
            "Error: no LLM client available. Set OPENAI_API_KEY to use the OpenAI adapter.",
            err=True,
        )
        sys.exit(2)

    try:
        report = reason_module.analyze(
            target=target,
            client=client,
            model=model,
            show_progress=not (ci or json_out),
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

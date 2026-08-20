"""Real-world corpus benchmark — the deterministic half, measured on real code.

The seed dataset in ``dataset/seed.yaml`` is self-authored, so it can only ever
be a regression guard (see SPYV-VERDICT-AND-PLAN T5). This module measures the
part of spyv that is provable — cross-framework prompt *discovery* and the regex
checkers — against real repositories, where the ground truth is the code itself
rather than a label the author wrote.

Three things get measured, none of which needs an API key or an LLM:

  yield        how many prompts discovery finds in real code, broken down by the
               construct they were found in (CrewAI agent, OpenAI message,
               f-string, YAML, ...). Descriptive: no labels required.

  agreement    discovery against a deliberately naive grep baseline -- what an
               engineer would find with 'grep -ri "you are"'. Reported as a
               three-way split (both / spyv-only / grep-only). spyv-only is the
               value discovery adds; grep-only is where discovery may be missing
               something and is the honest half of the comparison.

  exposure     deterministic checker hits on the prompts found in real code:
               hardcoded credentials and personal data actually sitting in
               committed prompts.

Evidence is redacted by default. A real credential found in a public repository
is still a live credential, so the value is never written to the report unless
the caller explicitly asks -- and even then it belongs in a private triage file,
not in a published number. Report counts, not secrets.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# A deliberately naive baseline: what a developer grepping for prompts would
# plausibly type. Kept simple on purpose -- making it clever would understate
# the value discovery adds, and making it useless would overstate it.
_GREP_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"you are (?:a|an|the)\b", re.IGNORECASE),
    re.compile(r"\bsystem_prompt\b", re.IGNORECASE),
    re.compile(r"\bSYSTEM_PROMPT\b"),
    re.compile(r"\bsystem_message\b", re.IGNORECASE),
    re.compile(r'"role"\s*:\s*"system"'),
    re.compile(r"'role'\s*:\s*'system'"),
    re.compile(r"\bbackstory\s*=", re.IGNORECASE),
    re.compile(r"\binstructions\s*=", re.IGNORECASE),
)

_TEXT_SUFFIXES = frozenset(
    {".py", ".yaml", ".yml", ".json", ".md", ".txt", ".toml", ".cfg", ".ini", ".j2", ".jinja"}
)

_SKIP_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
        "site-packages", ".eggs", ".next", "target",
    }
)

_MAX_FILE_BYTES = 2_000_000


def redact(value: str, keep: int = 4) -> str:
    """Mask the middle of a matched value so a report can name a hit without leaking it."""
    if len(value) <= keep:
        return "*" * len(value)
    if len(value) <= keep * 2:
        return value[:keep] + "*" * (len(value) - keep)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"


def _walk_text_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        out.append(path)
    return out


def grep_candidate_files(root: Path) -> set[str]:
    """Files a naive grep for prompt markers would surface, as posix-relative paths."""
    hits: set[str] = set()
    root = Path(root)
    for path in _walk_text_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(m.search(text) for m in _GREP_MARKERS):
            try:
                hits.add(path.relative_to(root).as_posix())
            except ValueError:
                hits.add(path.as_posix())
    return hits


@dataclass
class RepoResult:
    name: str
    path: str
    files_scanned: int = 0
    prompts_found: int = 0
    prompt_files: set[str] = field(default_factory=set)
    grep_files: set[str] = field(default_factory=set)
    by_source_kind: Counter[str] = field(default_factory=Counter)
    checker_hits: Counter[str] = field(default_factory=Counter)
    exposed_prompts: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def both(self) -> set[str]:
        return self.prompt_files & self.grep_files

    @property
    def spyv_only(self) -> set[str]:
        return self.prompt_files - self.grep_files

    @property
    def grep_only(self) -> set[str]:
        return self.grep_files - self.prompt_files

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "files_scanned": self.files_scanned,
            "prompts_found": self.prompts_found,
            "prompt_files": len(self.prompt_files),
            "by_source_kind": dict(sorted(self.by_source_kind.items())),
            "agreement": {
                "both": len(self.both),
                "spyv_only": len(self.spyv_only),
                "grep_only": len(self.grep_only),
                "grep_only_files": sorted(self.grep_only)[:20],
            },
            "exposure": {
                "prompts_with_hits": self.exposed_prompts,
                "by_checker": dict(sorted(self.checker_hits.items())),
            },
            "findings": self.findings,
            "error": self.error,
        }


def run_repo(root: str | Path, *, name: str | None = None, reveal: bool = False) -> RepoResult:
    """Discovery + deterministic checkers over one real repository."""
    from ..checkers import run_checkers
    from ..discovery import discover

    root_path = Path(root)
    result = RepoResult(name=name or root_path.name, path=str(root_path))
    if not root_path.exists():
        result.error = "path not found"
        return result

    try:
        discovered, files_scanned = discover(root_path)
    except (OSError, ValueError) as exc:
        result.error = f"discovery failed: {exc}"
        return result

    result.files_scanned = files_scanned
    result.prompts_found = len(discovered)

    for d in discovered:
        try:
            rel = Path(d.file).resolve().relative_to(root_path.resolve()).as_posix()
        except (ValueError, OSError):
            rel = Path(d.file).as_posix()
        result.prompt_files.add(rel)
        result.by_source_kind[d.source_kind] += 1

        # The prompt text is scanned as if it were output: an embedded credential
        # or personal datum fires the same checkers that guard runtime output.
        hits = run_checkers("", d.system_prompt)
        if hits:
            result.exposed_prompts += 1
            for h in hits:
                result.checker_hits[f"{h.checker}/{h.label}"] += 1
            result.findings.append(
                {
                    "file": rel,
                    "line": d.line,
                    "identifier": d.identifier,
                    "source_kind": d.source_kind,
                    "hits": [
                        {
                            "checker": h.checker,
                            "label": h.label,
                            "severity": h.severity,
                            "evidence": h.evidence if reveal else redact(h.evidence),
                        }
                        for h in hits
                    ],
                }
            )

    result.grep_files = grep_candidate_files(root_path)
    return result


def run_corpus(
    roots: list[str | Path], *, names: list[str] | None = None, reveal: bool = False
) -> dict[str, Any]:
    """Run the corpus benchmark over several repositories."""
    results: list[RepoResult] = []
    for i, root in enumerate(roots):
        name = names[i] if names and i < len(names) else None
        results.append(run_repo(root, name=name, reveal=reveal))

    ok = [r for r in results if r.error is None]
    totals = {
        "repos": len(results),
        "repos_ok": len(ok),
        "files_scanned": sum(r.files_scanned for r in ok),
        "prompts_found": sum(r.prompts_found for r in ok),
        "prompt_files": sum(len(r.prompt_files) for r in ok),
        "agreement": {
            "both": sum(len(r.both) for r in ok),
            "spyv_only": sum(len(r.spyv_only) for r in ok),
            "grep_only": sum(len(r.grep_only) for r in ok),
        },
        "exposure": {
            "prompts_with_hits": sum(r.exposed_prompts for r in ok),
            "by_checker": dict(sorted(sum((r.checker_hits for r in ok), Counter()).items())),
        },
        "by_source_kind": dict(sorted(sum((r.by_source_kind for r in ok), Counter()).items())),
    }
    return {
        "benchmark": "corpus",
        "reproducible": True,
        "evidence_redacted": not reveal,
        "totals": totals,
        "repos": [r.to_dict() for r in results],
    }


def format_corpus_report(results: dict[str, Any]) -> str:
    t = results["totals"]
    lines: list[str] = []
    lines.append("=" * 68)
    lines.append("SPYV CORPUS BENCHMARK  (deterministic, no LLM, reproducible)")
    lines.append("=" * 68)
    lines.append(
        f"repos: {t['repos_ok']}/{t['repos']} ok     files scanned: {t['files_scanned']}     "
        f"prompts found: {t['prompts_found']} in {t['prompt_files']} files"
    )
    lines.append("")

    if t["by_source_kind"]:
        lines.append("-- discovery yield by construct " + "-" * 36)
        for kind, n in sorted(t["by_source_kind"].items(), key=lambda kv: -kv[1]):
            lines.append(f"   {kind:<20} {n}")
        lines.append("")

    a = t["agreement"]
    total_files = a["both"] + a["spyv_only"] + a["grep_only"]
    lines.append("-- agreement with a naive grep baseline " + "-" * 28)
    lines.append(f"   both found          {a['both']}")
    lines.append(f"   spyv only           {a['spyv_only']}   <- value discovery adds")
    lines.append(f"   grep only           {a['grep_only']}   <- inspect: possible discovery misses")
    if total_files:
        lines.append(
            f"   spyv share of all prompt-bearing files: "
            f"{(a['both'] + a['spyv_only']) / total_files * 100:.0f}%"
        )
    lines.append("")

    e = t["exposure"]
    lines.append("-- exposure in real prompts " + "-" * 40)
    lines.append(f"   prompts containing a checker hit: {e['prompts_with_hits']}")
    for checker, n in sorted(e["by_checker"].items(), key=lambda kv: -kv[1]):
        lines.append(f"   {checker:<28} {n}")
    lines.append("")

    failed = [r for r in results["repos"] if r["error"]]
    if failed:
        lines.append("-- repos skipped " + "-" * 50)
        for r in failed:
            lines.append(f"   {r['name']}: {r['error']}")
        lines.append("")

    if results["evidence_redacted"]:
        lines.append("Evidence is REDACTED. A credential in a public repo is still live:")
        lines.append("report counts, not secrets. --reveal writes values to a local file only.")
    else:
        lines.append("WARNING: evidence is UNREDACTED. Treat this output as sensitive; do not")
        lines.append("commit or publish it, and disclose findings to the repo owner privately.")
    lines.append("")
    lines.append("Yield and exposure are descriptive (no labels needed). The grep comparison")
    lines.append("is an agreement analysis, not a recall estimate -- grep is not ground truth.")
    return "\n".join(lines)


__all__ = [
    "RepoResult",
    "format_corpus_report",
    "grep_candidate_files",
    "redact",
    "run_corpus",
    "run_repo",
]

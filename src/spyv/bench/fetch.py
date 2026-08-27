"""Fetch the public corpus.

Only repositories listed in the manifest are cloned, and only over http(s).
Local paths are rejected by construction, so a private or employer codebase
cannot be pulled into a measurement even by accident -- the corpus has to be
reproducible by a stranger, and that is only true if every input is public.

Clones are shallow and the resolved commit is recorded, so a rerun measures the
same bytes and the reported number can be checked against a specific SHA.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path(__file__).parent / "corpus_manifest.yaml"
DEFAULT_CACHE = Path.home() / ".cache" / "spyv" / "corpus"

_ALLOWED_SCHEMES = ("https://", "http://")


class UnsafeSource(ValueError):
    """Raised when a manifest entry is not a public remote URL."""


@dataclass
class RepoRef:
    name: str
    url: str
    framework: str = "unknown"
    sha: str = ""
    # A repository that exists wholly to demonstrate. Path classification cannot
    # detect this: an examples collection's internal paths look ordinary, so no
    # directory component marks them. Declared per repository instead.
    demonstrative: bool = False
    # Which selection process produced this entry. The original twenty were
    # chosen by convenience and the expansion mechanically, so a mixed corpus
    # has no single sampling interpretation and the two must stay separable.
    cohort: str = "original"
    path: Path | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "framework": self.framework,
            "sha": self.sha,
            "demonstrative": self.demonstrative,
            "cohort": self.cohort,
            "error": self.error,
        }


def load_manifest(path: str | Path | None = None) -> list[RepoRef]:
    import yaml

    manifest_path = Path(path or DEFAULT_MANIFEST)
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    refs: list[RepoRef] = []
    for entry in data.get("repos", []) or []:
        url = str(entry.get("url", ""))
        if not url.startswith(_ALLOWED_SCHEMES):
            raise UnsafeSource(
                f"{entry.get('name')!r}: only public http(s) URLs may be measured, got {url!r}"
            )
        refs.append(
            RepoRef(
                name=str(entry["name"]),
                url=url,
                framework=str(entry.get("framework", "unknown")),
                sha=str(entry.get("sha") or ""),
                demonstrative=bool(entry.get("demonstrative", False)),
                cohort=str(entry.get("cohort", "original")),
            )
        )
    return refs


def _run(args: list[str], cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


def fetch_repo(ref: RepoRef, cache: Path) -> RepoRef:
    """Shallow-clone one public repository and record the commit actually measured."""
    if not ref.url.startswith(_ALLOWED_SCHEMES):
        ref.error = "refused: not a public http(s) URL"
        return ref

    target = cache / ref.name
    try:
        if not (target / ".git").exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            args = ["git", "clone", "--quiet", "--filter=blob:none", "--depth", "1"]
            if ref.sha:
                # A pinned sha needs history, so fetch it explicitly after cloning.
                args = ["git", "clone", "--quiet", "--filter=blob:none"]
            args += [ref.url, str(target)]
            proc = _run(args)
            if proc.returncode != 0:
                ref.error = f"clone failed: {(proc.stderr or '').strip()[:200]}"
                return ref

        if ref.sha:
            proc = _run(["git", "checkout", "--quiet", ref.sha], cwd=target)
            if proc.returncode != 0:
                ref.error = f"checkout {ref.sha[:8]} failed: {(proc.stderr or '').strip()[:200]}"
                return ref

        proc = _run(["git", "rev-parse", "HEAD"], cwd=target)
        if proc.returncode == 0:
            ref.sha = proc.stdout.strip()
        ref.path = target
    except (OSError, subprocess.SubprocessError) as exc:
        ref.error = f"{type(exc).__name__}: {exc}"
    return ref


def fetch_corpus(
    manifest: str | Path | None = None,
    cache: str | Path | None = None,
    *,
    limit: int | None = None,
) -> list[RepoRef]:
    cache_dir = Path(cache or DEFAULT_CACHE)
    refs = load_manifest(manifest)
    if limit is not None:
        refs = refs[:limit]
    return [fetch_repo(ref, cache_dir) for ref in refs]


__all__ = [
    "DEFAULT_CACHE",
    "DEFAULT_MANIFEST",
    "RepoRef",
    "UnsafeSource",
    "fetch_corpus",
    "fetch_repo",
    "load_manifest",
]

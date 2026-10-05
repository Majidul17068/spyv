"""Estimate what the extractor never saw, by sampling files rather than sites.

Pre-registered in PROTOCOL_MISSED_SITES.md before this module was written.

`annotate` draws candidates the detector already produced, so it measures whether
recognised occurrences are real and correctly classified. It cannot measure what
was never enumerated: a sample conditioned on the detector's output has no way to
contain a site the detector missed. Every yield figure in this work is conditional
on that inventory, and that conditioning is the largest unquantified assumption in
the measurement.

This module builds the other frame. It enumerates files, draws a probability
sample of them, and records what a person finds by reading each one -- detected or
not. The sample is stratified by whether the detector found anything in the file,
which is legitimate because every file keeps a known non-zero inclusion
probability and the estimator weights by it. Stratum B, the files with no detected
candidate, is the only place a wholly-missed file can appear, so it is sampled at
a rate that can actually find one.

    spyv missed-sites draw --out files.json      # draw the file sample
    spyv missed-sites label files.json           # record what you find
    spyv missed-sites score files.json           # weighted estimate

The labels are a person's. Nothing here generates them.
"""

from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..discovery import _SKIP_DIRS
from .scaffolding import classify_path

SAMPLE_SEED = 20260924


@dataclass
class FileRecord:
    """One file in the sampling frame.

    ``parse_ok`` is carried rather than used to filter. A file the extractor
    could not parse is a file whose sites were all missed, and dropping it from
    the frame would hide exactly the failure this audit exists to find.
    """

    repo: str
    path: str
    stratum: str  # "production" | "scaffolding"
    lines: int
    detected: int  # candidates the extractor enumerated in this file
    parse_ok: bool
    read_error: str = ""

    @property
    def arm(self) -> str:
        """Sampling stratum: A has detected candidates, B has none."""
        return "A" if self.detected > 0 else "B"


def enumerate_frame(cache: Path | None = None, repos: list[str] | None = None) -> list[FileRecord]:
    """Every in-frame file across the corpus, with its detected-candidate count.

    The enumeration matches the corrective measurement's: tracked Python files
    under the pinned checkouts, minus the standard skip directories. Symlinks are
    excluded so a file is not counted twice under two paths.
    """
    from .fetch import DEFAULT_CACHE, load_manifest

    root = cache or DEFAULT_CACHE
    wanted = set(repos) if repos else None
    out: list[FileRecord] = []

    # Corpus sources raise their own SyntaxWarnings on parse. They are the
    # subject, not a defect in this tool, and they drown the report.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        _collect(load_manifest(), root, wanted, out)
    return out


def _collect(refs: list[Any], root: Path, wanted: set[str] | None, out: list[FileRecord]) -> None:
    from .visibility import sites_in_source

    for ref in refs:
        if wanted is not None and ref.name not in wanted:
            continue
        repo_root = root / ref.name
        if not repo_root.exists():
            continue
        for path in sorted(repo_root.rglob("*.py")):
            if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
                continue
            if path.is_symlink():
                continue
            rel = path.relative_to(repo_root).as_posix()
            record = FileRecord(
                repo=ref.name,
                path=rel,
                stratum=classify_path(rel),
                lines=0,
                detected=0,
                parse_ok=False,
            )
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                record.read_error = type(exc).__name__
                out.append(record)
                continue
            record.lines = source.count("\n") + 1
            try:
                ast.parse(source)
            except (SyntaxError, ValueError):
                out.append(record)
                continue
            record.parse_ok = True
            record.detected = len(sites_in_source(source, rel))
            out.append(record)


def frame_summary(frame: list[FileRecord]) -> dict[str, object]:
    """Counts a reader needs to judge the sample before seeing any label."""
    arms: dict[str, int] = {"A": 0, "B": 0}
    strata: dict[str, int] = {"production": 0, "scaffolding": 0}
    for f in frame:
        arms[f.arm] += 1
        strata[f.stratum] = strata.get(f.stratum, 0) + 1
    return {
        "files": len(frame),
        "repos": len({f.repo for f in frame}),
        "by_arm": arms,
        "by_stratum": strata,
        "unparseable": sum(1 for f in frame if not f.parse_ok and not f.read_error),
        "unreadable": sum(1 for f in frame if f.read_error),
        "detected_candidates": sum(f.detected for f in frame),
    }


# ---------------------------------------------------------------------------
# sampling
# ---------------------------------------------------------------------------
#: Why a site a reviewer found was not enumerated. Fixed by protocol; a cause
#: outside this list is recorded as ``other`` with a note rather than invented.
MISS_CAUSES = frozenset({
    "unsupported_api",      # a framework or SDK entry point the extractor has no rule for
    "alias",                # the construct is reached under a name the rules do not match
    "dynamic_construction", # built at run time from parts no static reader holds
    "config_driven",        # the text lives in configuration the extractor does not read
    "hint_miss",            # a recognised shape whose parameter name is not in the hint list
    "parse_failure",        # the whole file was unreadable to the parser
    "other",
})


@dataclass
class FoundSite:
    """One instruction-bearing site a reviewer found by reading the file."""

    line: int
    construct: str
    status: str  # "detected" | "missed"
    cause: str = ""
    confidence: str = "certain"  # "certain" | "uncertain"
    note: str = ""


@dataclass
class SampledFile:
    """A drawn file, its inclusion probability, and the reviewer's record.

    The weight travels with the file. An estimate computed without it would
    describe the sample's arm mix rather than the corpus, and the arm mix here is
    deliberately nothing like the corpus's.
    """

    repo: str
    path: str
    stratum: str
    arm: str
    lines: int
    detected: int
    parse_ok: bool
    inclusion_prob: float
    # reviewer's record
    reviewed: bool = False
    no_instruction_text: bool | None = None
    found: list[FoundSite] = field(default_factory=list)
    label_source: str = "human"  # "human" | "ai_assisted"
    note: str = ""

    @property
    def weight(self) -> float:
        """Horvitz-Thompson weight: how many frame files this one stands for."""
        return 1.0 / self.inclusion_prob if self.inclusion_prob > 0 else 0.0

    @property
    def missed(self) -> int:
        return sum(1 for s in self.found if s.status == "missed")

    @property
    def sites(self) -> int:
        return len(self.found)


def draw_sample(
    frame: list[FileRecord],
    *,
    n_a: int = 60,
    n_b: int = 60,
    seed: int = SAMPLE_SEED,
) -> list[SampledFile]:
    """Draw a stratified probability sample of files, recording each one's odds.

    Simple random sampling without replacement inside each arm, so the inclusion
    probability is the arm's sampling fraction and every file in the frame has a
    known non-zero chance of being read. Nothing about a file's *content* steers
    the draw -- only whether the detector fired in it, which is what the weights
    then undo.
    """
    import random

    rng = random.Random(seed)
    pools: dict[str, list[FileRecord]] = {"A": [], "B": []}
    for record in frame:
        pools[record.arm].append(record)

    out: list[SampledFile] = []
    for arm, want in (("A", n_a), ("B", n_b)):
        pool = pools[arm]
        if not pool:
            continue
        take = min(want, len(pool))
        prob = take / len(pool)
        for record in rng.sample(pool, take):
            out.append(SampledFile(
                repo=record.repo,
                path=record.path,
                stratum=record.stratum,
                arm=arm,
                lines=record.lines,
                detected=record.detected,
                parse_ok=record.parse_ok,
                inclusion_prob=prob,
            ))
    rng.shuffle(out)
    return out


__all__ = [
    "MISS_CAUSES",
    "SAMPLE_SEED",
    "FileRecord",
    "FoundSite",
    "SampledFile",
    "draw_sample",
    "enumerate_frame",
    "frame_summary",
]

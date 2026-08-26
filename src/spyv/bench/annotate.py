"""Human validation of prompt-site detection.

The visibility metric's denominator is whatever our detectors enumerate, so every
figure derived from it inherits their precision. Nothing in the pipeline checks
that a site the detector calls a prompt site is one, or that a visibility class is
right. This module draws the sample, records human judgements, and computes the
agreement statistics that turn "our parser says so" into a measured precision.

Sampling is stratified by construct and by visibility class and seeded, so the
same sample is drawn on every machine and the labels are checkable against it.

    spyv annotate --sample 400 --out labels.json     # draw and label
    spyv annotate --resume labels.json               # continue where you left off
    spyv annotate --score labels.json                # precision, recall, agreement

On agreement. Cohen's kappa needs two annotators who labelled independently. With
one annotator the tool computes precision and recall and reports no kappa, and
says so in the output rather than leaving the reader to notice. A single-annotator
result is a real validation and should be described as one -- not dressed up as
inter-rater agreement it does not have.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SAMPLE_SEED = 20260826
CONTEXT_LINES = 6


@dataclass
class Item:
    """One sampled site awaiting or carrying a judgement."""

    repo: str
    file: str
    line: int
    construct: str
    framework: str
    predicted_visibility: str
    predicted_text: str = ""
    snippet: str = ""
    # human judgements, filled in during labelling
    is_prompt_site: bool | None = None
    true_visibility: str | None = None
    note: str = ""

    @property
    def labelled(self) -> bool:
        return self.is_prompt_site is not None


def draw_sample(n: int, *, seed: int = SAMPLE_SEED, cache: Path | None = None) -> list[Item]:
    """Stratified sample across construct x predicted visibility.

    Stratifying matters: a uniform draw would be dominated by the two constructs
    that supply most sites, and would barely test the classes where the detector
    is most likely to be wrong.
    """
    from .fetch import DEFAULT_CACHE, load_manifest
    from .visibility import run_visibility

    root = cache or DEFAULT_CACHE
    strata: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for ref in load_manifest():
        path = root / ref.name
        if not path.exists():
            continue
        for site in run_visibility(path, name=ref.name).sites:
            strata[(site.construct, site.visibility)].append(
                Item(repo=ref.name, file=site.file, line=site.line,
                     construct=site.construct, framework=site.framework,
                     predicted_visibility=site.visibility,
                     predicted_text=site.text[:400])
            )
    if not strata:
        return []

    rng = random.Random(seed)
    # Proportional allocation with a floor, so small strata are still tested.
    total = sum(len(v) for v in strata.values())
    picked: list[Item] = []
    for key in sorted(strata):
        pool = strata[key]
        want = max(2, round(n * len(pool) / total))
        picked.extend(rng.sample(pool, min(want, len(pool))))
    rng.shuffle(picked)
    return picked[:n]


def attach_snippets(items: list[Item], cache: Path | None = None) -> None:
    """Read the surrounding source so a labeller can judge without leaving the tool."""
    from .fetch import DEFAULT_CACHE

    root = cache or DEFAULT_CACHE
    for item in items:
        path = root / item.repo / item.file
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        lo = max(0, item.line - 1 - CONTEXT_LINES)
        hi = min(len(lines), item.line + CONTEXT_LINES)
        out = []
        for i in range(lo, hi):
            marker = ">>" if i == item.line - 1 else "  "
            out.append(f"{marker} {i+1:>5} | {lines[i][:160]}")
        item.snippet = "\n".join(out)


def save(items: list[Item], path: Path, meta: dict[str, Any] | None = None) -> None:
    path.write_text(json.dumps({
        "seed": SAMPLE_SEED,
        "meta": meta or {},
        "items": [asdict(i) for i in items],
    }, indent=2), encoding="utf-8")


def load(path: Path) -> tuple[list[Item], dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Item(**d) for d in data["items"]], data.get("meta", {})


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def cohens_kappa(a: list[str], b: list[str]) -> float:
    """Chance-corrected agreement between two independent label sequences."""
    if not a or len(a) != len(b):
        return 0.0
    n = len(a)
    observed = sum(1 for x, y in zip(a, b, strict=False) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum((ca[k] / n) * (cb[k] / n) for k in set(a) | set(b))
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def score(items: list[Item], second_pass: list[Item] | None = None) -> dict[str, Any]:
    """Precision of site detection and of visibility classification.

    Recall against the true population is NOT estimated here and cannot be: it
    would require finding prompt sites the detector missed, which needs a
    different sampling frame (a sample of source locations, not of detections).
    Reporting precision as though it were recall would overstate the result, so
    the field is named and left absent.
    """
    done = [i for i in items if i.labelled]
    if not done:
        return {"labelled": 0, "note": "no labels yet"}

    true_sites = [i for i in done if i.is_prompt_site]
    site_precision = len(true_sites) / len(done)

    vis_correct = sum(1 for i in true_sites
                      if i.true_visibility and i.true_visibility == i.predicted_visibility)
    vis_accuracy = vis_correct / len(true_sites) if true_sites else 0.0

    by_construct: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "true": 0})
    for i in done:
        by_construct[i.construct]["n"] += 1
        by_construct[i.construct]["true"] += int(bool(i.is_prompt_site))

    confusion: Counter[tuple[str, str]] = Counter()
    for i in true_sites:
        if i.true_visibility:
            confusion[(i.predicted_visibility, i.true_visibility)] += 1

    out: dict[str, Any] = {
        "labelled": len(done),
        "site_precision": site_precision,
        "visibility_accuracy": vis_accuracy,
        "by_construct": {k: dict(v) for k, v in sorted(by_construct.items())},
        "confusion_predicted_vs_true": {f"{a}->{b}": c for (a, b), c in sorted(confusion.items())},
        "recall": None,
        "recall_note": ("Not estimable from this sample. Recall requires a frame of source "
                        "locations rather than of detections; this sample can only measure "
                        "precision."),
        "annotators": 1,
        "kappa": None,
        "kappa_note": ("Cohen's kappa requires two annotators labelling independently. "
                       "With one annotator no agreement statistic is computed, and the "
                       "result should be reported as single-annotator validation."),
    }

    if second_pass:
        by_key = {(i.repo, i.file, i.line, i.construct): i for i in second_pass if i.labelled}
        pairs = [(i, by_key[(i.repo, i.file, i.line, i.construct)])
                 for i in done if (i.repo, i.file, i.line, i.construct) in by_key]
        if pairs:
            out["annotators"] = 2
            out["n_paired"] = len(pairs)
            out["kappa"] = cohens_kappa([str(a.is_prompt_site) for a, _ in pairs],
                                        [str(b.is_prompt_site) for _, b in pairs])
            out["kappa_visibility"] = cohens_kappa(
                [a.true_visibility or "" for a, _ in pairs],
                [b.true_visibility or "" for _, b in pairs])
            out["kappa_note"] = ("Computed from two independently labelled passes. If both "
                                 "passes were produced by the same person, this is "
                                 "intra-rater (test-retest) agreement, not inter-rater, and "
                                 "must be reported as such.")
    return out


__all__ = ["Item", "attach_snippets", "cohens_kappa", "draw_sample", "load", "save", "score"]

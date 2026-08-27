"""Does prompt opacity have a security consequence?

Implements PROTOCOL_CONSEQUENCE.md. Interpolating a runtime value into
instruction text is the precondition for prompt injection, and a static check for
it can only fire where the prompt is readable. This measures the recall of that
check against runtime ground truth, and decomposes the misses into sites the
analyser could not read and sites it read and judged wrongly.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .runtime import Observation, _canonical_construct, _resolve, _site_matches_line

MIN_FOR_RATE = 10  # per protocol: no rate on single-digit denominators


@dataclass
class SiteEvidence:
    """What runtime showed about one authoring site."""

    file: str
    line: int
    construct: str
    visibility: str
    texts: set[str] = field(default_factory=set)
    observations: int = 0

    @property
    def verdict(self) -> str:
        """interpolating | constant | undetermined.

        A site seen once cannot be distinguished from a constant, so it is
        excluded from both numerator and denominator rather than assumed either
        way.
        """
        if len(self.texts) >= 2:
            return "interpolating"
        if self.observations >= 2:
            return "constant"
        return "undetermined"


def ground_truth(
    observations: list[Observation], sites: list[Any]
) -> tuple[dict[tuple, SiteEvidence], int]:
    """Group observations by authoring site, never by innermost frame.

    A framework that re-materialises many callers' agents through one internal
    line would otherwise look like a single wildly-varying site, which measures
    the framework rather than the code that wrote the prompt.

    Returns the evidence and the count of observations that could not be pinned
    to one enumerated expression.
    """
    by_key: dict[tuple[str, str], list[Any]] = {}
    for site in sites:
        by_key.setdefault((site.file, _canonical_construct(site.construct)), []).append(site)

    evidence: dict[tuple, SiteEvidence] = {}
    unresolvable = 0
    for obs in observations:
        found = _resolve(obs, by_key)
        if found is None:
            continue
        site, depth = found
        # The same span discipline compare() applies. Without it, observations
        # from many different constructions in one file collapse onto whichever
        # site is nearest by line, and a set of unrelated prompts becomes
        # indistinguishable from one site that interpolates -- manufacturing the
        # very finding this experiment exists to measure.
        frame_line = obs.stack[depth][1] if obs.stack else obs.line
        if not _site_matches_line(site, frame_line):
            unresolvable += 1
            continue
        key = (site.file, site.line, site.construct)
        ev = evidence.get(key)
        if ev is None:
            ev = SiteEvidence(file=site.file, line=site.line, construct=site.construct,
                              visibility=site.visibility)
            evidence[key] = ev
        ev.texts.add(obs.text)
        ev.observations += 1
    return evidence, unresolvable


def evaluate(observations: list[Observation], sites: list[Any], repo: str = "") -> dict[str, Any]:
    """Recall of the prompt-injection precondition check, and why it misses."""
    evidence, unresolvable = ground_truth(observations, sites)
    buckets: dict[str, list[SiteEvidence]] = defaultdict(list)
    for ev in evidence.values():
        buckets[ev.verdict].append(ev)

    interpolating = buckets["interpolating"]
    # `partial` is the analyser's own claim that a site interpolates.
    detected = [e for e in interpolating if e.visibility == "partial"]
    missed_opaque = [e for e in interpolating if e.visibility == "opaque"]
    missed_static = [e for e in interpolating if e.visibility == "static"]

    n = len(interpolating)
    out: dict[str, Any] = {
        "repo": repo,
        "sites_with_runtime_evidence": len(evidence),
        "interpolating": n,
        "constant": len(buckets["constant"]),
        "undetermined": len(buckets["undetermined"]),
        "observations_not_line_resolvable": unresolvable,
        "detected": len(detected),
        "missed_opaque": len(missed_opaque),
        "missed_read_but_judged_constant": len(missed_static),
        "enough_for_a_rate": n >= MIN_FOR_RATE,
    }
    if n >= MIN_FOR_RATE:
        from .study import wilson

        lo, hi = wilson(len(detected), n)
        out["recall"] = len(detected) / n
        out["recall_ci95"] = [lo, hi]
        out["share_of_misses_structural"] = (
            len(missed_opaque) / (n - len(detected)) if n > len(detected) else None
        )
    else:
        out["recall"] = None
        out["note"] = (
            f"fewer than {MIN_FOR_RATE} interpolating sites; counts reported without a "
            "rate, per protocol. A recall percentage on a single-digit denominator is "
            "noise presented as a measurement."
        )
    out["examples"] = [
        {"file": e.file, "line": e.line, "construct": e.construct,
         "visibility": e.visibility, "distinct_texts": len(e.texts),
         "sample": sorted(e.texts)[:2]}
        for e in (missed_opaque + missed_static)[:10]
    ]
    return out


__all__ = ["SiteEvidence", "evaluate", "ground_truth"]

"""What is actually in the prompts a static reader can recover.

Implements PROTOCOL_CONTENT.md, committed before this file existed.

The measure that decides whether any of this is worth reporting is M1, and the
thing that decides whether M1 is worth anything is placeholder handling. Public
repositories are full of `sk-YOUR-KEY-HERE` and the documented AWS example key.
A count that treats those as credential exposure produces a striking number that
happens to be false, so every hit is classified before it is counted and all
classes are published.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..checkers import CheckerHit, check_pii, check_secrets
from .visibility import PromptSite, run_visibility

HitClass = Literal["placeholder", "low_entropy", "context_excluded", "plausible"]

# Entropy below this is not a credential. Real provider keys are base62-ish and
# sit far above it; `YOUR_API_KEY_HERE` and `xxxxxxxx` sit far below.
ENTROPY_FLOOR = 3.0

_PLACEHOLDER_WORDS = (
    "your", "example", "sample", "dummy", "fake", "placeholder", "changeme",
    "change_me", "todo", "fixme", "insert", "replace", "here", "xxx", "abc123",
    "foo", "bar", "test", "mock", "redacted", "notreal", "mykey", "apikey",
)
# The AWS documentation key, which appears verbatim in a great many repositories.
_KNOWN_EXAMPLE_SECRETS = ("AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")

_PLACEHOLDER_SHAPE = re.compile(r"^[<{\[].*[>}\]]$")
_REPEATED_CHAR = re.compile(r"(.)\1{5,}")

_CONTEXT_EXCLUDED = (
    "test", "tests", "testing", "example", "examples", "sample", "samples",
    "doc", "docs", "documentation", "fixture", "fixtures", "benchmark",
    "benchmarks", "demo", "demos", "tutorial", "tutorials", "cookbook",
)

# M3: templating in an otherwise-literal prompt.
_FORMAT_HOLE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}|\{\}|%\(([a-zA-Z_]\w*)\)s|%s\b")

# M4: keyword families fixed in advance.
_GUARDRAIL_FAMILIES: dict[str, tuple[str, ...]] = {
    "refusal": ("refuse", "decline", "do not answer", "don't answer", "you must not",
                "never provide", "politely decline", "say you cannot"),
    "scope_limit": ("only answer", "stay on topic", "out of scope", "限", "restrict yourself",
                    "do not discuss", "only respond to", "limited to"),
    "non_disclosure": ("do not reveal", "don't reveal", "never reveal", "do not share",
                       "keep confidential", "do not disclose", "never disclose",
                       "system prompt", "these instructions"),
    "no_fabrication": ("do not make up", "don't make up", "do not invent", "no hallucin",
                       "if you don't know", "if you do not know", "say you don't know"),
}


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


_PLACEHOLDER_RE = re.compile(
    r"(?:^|[^a-z0-9])(" + "|".join(_PLACEHOLDER_WORDS) + r")(?:[^a-z0-9]|$)"
)


def _has_placeholder_word(lowered: str) -> bool:
    """Match placeholder vocabulary on token boundaries.

    Bare substring containment classified `barbara.jones@acme.com` as a
    placeholder, because it contains "bar". Real addresses were being discarded
    as fake by an accident of spelling.
    """
    return bool(_PLACEHOLDER_RE.search(lowered))


def _path_is_excluded(file_path: str) -> bool:
    parts = [p.lower() for p in Path(file_path).parts]
    stem = Path(file_path).stem.lower()
    if any(p in _CONTEXT_EXCLUDED for p in parts):
        return True
    return stem.startswith("test_") or stem.endswith("_test")


def classify_hit(evidence: str, file_path: str, checker: str = "secrets") -> HitClass:
    """Sort a checker hit before it is counted. Order matters and is fixed here.

    Placeholder-ness first, because a placeholder in production code is still a
    placeholder. Then context, then entropy.

    Two corrections over the original ordering, both of which changed published
    counts. The entropy floor is a test for *credentials*: real provider keys are
    high-entropy and placeholders are not. It is meaningless for personal data,
    because most PII formats are structurally low-entropy -- the maximum
    attainable Shannon entropy of a ten-digit numeric string is log2(10) = 3.32,
    below which sit ordinary phone numbers, national identifiers and card
    numbers. Applying a credential threshold to them manufactured `low_entropy`
    verdicts on genuine PII, and both such verdicts in our published results were
    phone numbers. The floor now applies only to credential hits.

    Context is now tested before entropy, so a hit under a test or example path
    is attributed to the reason that actually disqualifies it rather than to
    whichever heuristic happens to fire first.
    """
    lowered = evidence.lower()
    if any(known.lower() in lowered for known in _KNOWN_EXAMPLE_SECRETS):
        return "placeholder"
    if _has_placeholder_word(lowered):
        return "placeholder"
    if _PLACEHOLDER_SHAPE.match(evidence.strip()) or _REPEATED_CHAR.search(evidence):
        return "placeholder"
    if _path_is_excluded(file_path):
        return "context_excluded"
    if checker == "secrets" and shannon_entropy(evidence) < ENTROPY_FLOOR:
        return "low_entropy"
    return "plausible"


@dataclass
class ContentResult:
    name: str
    recoverable_prompts: int = 0
    static_prompts: int = 0
    partial_prompts: int = 0
    secret_classes: Counter[str] = field(default_factory=Counter)
    pii_classes: Counter[str] = field(default_factory=Counter)
    prompts_with_plausible_secret: int = 0
    prompts_with_plausible_pii: int = 0
    interpolating_prompts: int = 0
    guardrail_prompts: int = 0
    guardrail_families: Counter[str] = field(default_factory=Counter)
    secret_labels: Counter[str] = field(default_factory=Counter)
    pii_labels: Counter[str] = field(default_factory=Counter)

    def metrics(self) -> dict[str, Any]:
        n = self.recoverable_prompts
        share = (lambda k: k / n if n else 0.0)  # noqa: E731
        return {
            "name": self.name,
            "recoverable_prompts": n,
            "static_prompts": self.static_prompts,
            "partial_prompts": self.partial_prompts,
            "m1_secrets": {
                "classes": dict(self.secret_classes),
                "prompts_with_plausible": self.prompts_with_plausible_secret,
                "plausible_share": share(self.prompts_with_plausible_secret),
                "by_label": dict(self.secret_labels),
            },
            "m2_pii": {
                "classes": dict(self.pii_classes),
                "prompts_with_plausible": self.prompts_with_plausible_pii,
                "plausible_share": share(self.prompts_with_plausible_pii),
                "by_label": dict(self.pii_labels),
            },
            "m3_interpolation": {
                "prompts": self.interpolating_prompts,
                "share": share(self.interpolating_prompts),
            },
            "m4_guardrails": {
                "prompts": self.guardrail_prompts,
                "share": share(self.guardrail_prompts),
                "families": dict(self.guardrail_families),
            },
        }


def _interpolates(site: PromptSite) -> bool:
    if site.visibility == "partial" or "{...}" in site.text:
        return True
    return bool(_FORMAT_HOLE.search(site.text))


def _guardrail_families_in(text: str) -> list[str]:
    lowered = text.lower()
    return [fam for fam, cues in _GUARDRAIL_FAMILIES.items() if any(c in lowered for c in cues)]


def analyze_sites(sites: list[PromptSite], *, name: str = "") -> ContentResult:
    result = ContentResult(name=name)
    for site in sites:
        if site.visibility == "opaque" or not site.text:
            continue
        result.recoverable_prompts += 1
        if site.visibility == "static":
            result.static_prompts += 1
        else:
            result.partial_prompts += 1

        secret_hits: list[CheckerHit] = check_secrets(site.text)
        pii_hits: list[CheckerHit] = check_pii(site.text)

        plausible_secret = False
        for hit in secret_hits:
            klass = classify_hit(hit.evidence, site.file, "secrets")
            result.secret_classes[klass] += 1
            if klass == "plausible":
                plausible_secret = True
                result.secret_labels[hit.label] += 1
        if plausible_secret:
            result.prompts_with_plausible_secret += 1

        plausible_pii = False
        for hit in pii_hits:
            klass = classify_hit(hit.evidence, site.file, "pii")
            result.pii_classes[klass] += 1
            if klass == "plausible":
                plausible_pii = True
                result.pii_labels[hit.label] += 1
        if plausible_pii:
            result.prompts_with_plausible_pii += 1

        if _interpolates(site):
            result.interpolating_prompts += 1

        families = _guardrail_families_in(site.text)
        if families:
            result.guardrail_prompts += 1
            for fam in families:
                result.guardrail_families[fam] += 1
    return result


def run_content(root: str | Path, *, name: str | None = None) -> dict[str, Any]:
    res = run_visibility(root, name=name)
    return analyze_sites(res.sites, name=res.name).metrics()


__all__ = [
    "ENTROPY_FLOOR",
    "ContentResult",
    "analyze_sites",
    "classify_hit",
    "run_content",
    "shannon_entropy",
]

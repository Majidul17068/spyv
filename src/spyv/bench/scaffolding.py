"""Stratify prompt sites by whether their file is demonstrative or production.

Pre-registered in PROTOCOL_SCAFFOLDING.md before this module was written. Pooling
tests, examples and documentation with production code produces a figure that
describes neither population, and it is the statistic most exposed to attack.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

# Exact directory names, per protocol. Component equality, never substring:
# substring matching would sweep in `latest/`, `contest/`, `docstring_utils.py`.
SCAFFOLD_DIRS = frozenset({
    "test", "tests", "testing", "example", "examples", "sample", "samples",
    "doc", "docs", "cookbook", "cookbooks", "notebook", "notebooks",
    "benchmark", "benchmarks", "demo", "demos", "tutorial", "tutorials",
    "e2e", "integration_tests", "fixtures", "recipes", "snippets", "scripts",
})

Stratum = str  # "production" | "scaffolding"


def classify_path(path: str) -> Stratum:
    """Which stratum does this file belong to?

    Nested placement does not rescue a file: `examples/myapp/src/agent.py` is
    scaffolding, because the whole subtree exists to demonstrate rather than run.
    """
    p = PurePosixPath(str(path).replace("\\", "/"))
    if any(part.lower() in SCAFFOLD_DIRS for part in p.parts[:-1]):
        return "scaffolding"
    name = p.name.lower()
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return "scaffolding"
    if name.endswith(".ipynb"):
        return "scaffolding"
    return "production"


def _rates(sites: list[Any]) -> dict[str, Any]:
    total = len(sites)
    c = Counter(s.visibility for s in sites)
    static, partial = c["static"], c["partial"]
    return {
        "sites": total,
        "static": static,
        "partial": partial,
        "opaque": c["opaque"],
        "spv_static": static / total if total else None,
        "spv_partial": (static + partial) / total if total else None,
    }


@dataclass
class StratifiedRepo:
    """One repository's sites split by stratum."""

    name: str
    production: list[Any] = field(default_factory=list)
    scaffolding: list[Any] = field(default_factory=list)

    @property
    def has_production(self) -> bool:
        """Zero, not a tuned minimum, per protocol."""
        return len(self.production) > 0

    def metrics(self) -> dict[str, Any]:
        total = len(self.production) + len(self.scaffolding)
        return {
            "repo": self.name,
            "all_paths": _rates(self.production + self.scaffolding),
            "production": _rates(self.production),
            "scaffolding": _rates(self.scaffolding),
            "scaffolding_share": len(self.scaffolding) / total if total else None,
            "has_production": self.has_production,
        }


def stratify(name: str, sites: Iterable[Any]) -> StratifiedRepo:
    out = StratifiedRepo(name=name)
    for site in sites:
        if classify_path(site.file) == "scaffolding":
            out.scaffolding.append(site)
        else:
            out.production.append(site)
    return out


__all__ = ["SCAFFOLD_DIRS", "StratifiedRepo", "classify_path", "stratify"]

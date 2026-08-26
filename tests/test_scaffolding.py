"""Scaffolding stratification, per PROTOCOL_SCAFFOLDING.md."""

from __future__ import annotations

import pytest

from spyv.bench.scaffolding import classify_path, stratify
from spyv.bench.visibility import PromptSite


@pytest.mark.parametrize("path", [
    "tests/test_agent.py", "lib/tests/helpers.py", "examples/demo.py",
    "docs/guide.py", "notebooks/tour.ipynb", "test_agent.py",
    "agent_test.py", "conftest.py", "benchmarks/run.py",
    "examples/myapp/src/agent.py", "scripts/seed.py",
])
def test_demonstrative_paths_are_scaffolding(path):
    assert classify_path(path) == "scaffolding"


@pytest.mark.parametrize("path", [
    "src/crewai/agent.py", "agent.py", "lib/core/prompts.py",
    # Substring matching would misfile every one of these.
    "latest/agent.py", "contest/agent.py", "docstring_utils.py",
    "src/testing_utils_helper.py", "src/documents/loader.py",
])
def test_production_paths_are_production(path):
    assert classify_path(path) == "production"


def test_windows_separators_are_handled():
    assert classify_path("lib\\tests\\test_x.py") == "scaffolding"


def test_directory_match_is_case_insensitive():
    assert classify_path("Docs/guide.py") == "scaffolding"


def _site(file, vis="static"):
    return PromptSite(file=file, line=1, framework="crewai",
                      construct="Agent.role", visibility=vis, text="x")


def test_stratify_splits_and_reports_share():
    r = stratify("demo", [
        _site("src/a.py"), _site("tests/test_a.py", "opaque"),
        _site("examples/b.py"),
    ])
    assert len(r.production) == 1 and len(r.scaffolding) == 2
    m = r.metrics()
    assert m["scaffolding_share"] == pytest.approx(2 / 3)
    assert m["production"]["spv_static"] == 1.0
    assert m["scaffolding"]["spv_static"] == pytest.approx(0.5)


def test_repo_with_no_production_sites_is_flagged():
    r = stratify("examples-only", [_site("examples/a.py")])
    assert r.has_production is False
    assert r.metrics()["production"]["spv_static"] is None


def test_rates_are_none_not_zero_for_an_empty_stratum():
    """A missing rate must not be reported as a real 0.0 measurement."""
    r = stratify("x", [_site("src/a.py")])
    assert r.metrics()["scaffolding"]["spv_static"] is None

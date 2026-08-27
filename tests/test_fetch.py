"""Corpus fetching, and the guard that keeps non-public code out of measurements."""

from __future__ import annotations

import pytest

from spyv.bench.fetch import DEFAULT_MANIFEST, RepoRef, UnsafeSource, fetch_repo, load_manifest


def _manifest(tmp_path, body: str):
    p = tmp_path / "m.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# --- the safety guard -------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "/Users/someone/private-repo",
        "~/work/internal",
        "file:///srv/company/code",
        "../../elsewhere",
        "git@github.com:org/private.git",
        "ssh://git@internal.corp/repo.git",
        "",
    ],
)
def test_non_public_sources_are_refused(tmp_path, url):
    """A private or employer codebase must not be measurable even by accident.

    The corpus number is only reproducible by a stranger if every input is
    public, so this is enforced in code rather than by convention.
    """
    value = url if url else '""'
    m = _manifest(tmp_path, "repos:\n  - name: x\n    url: " + value + "\n")
    with pytest.raises(UnsafeSource):
        load_manifest(m)


@pytest.mark.parametrize("url", ["https://github.com/org/repo", "http://example.com/r.git"])
def test_public_urls_are_accepted(tmp_path, url):
    m = _manifest(tmp_path, f"repos:\n  - name: x\n    url: {url}\n")
    assert load_manifest(m)[0].url == url


def test_fetch_repo_refuses_a_non_public_ref_without_touching_the_network(tmp_path):
    ref = fetch_repo(RepoRef(name="x", url="/private/path"), tmp_path)
    assert ref.error is not None
    assert "refused" in ref.error
    assert ref.path is None


# --- manifest parsing -------------------------------------------------------


def test_shipped_manifest_is_valid_and_public_only():
    refs = load_manifest(DEFAULT_MANIFEST)
    assert len(refs) >= 20
    assert all(r.url.startswith(("https://", "http://")) for r in refs)
    assert len({r.name for r in refs}) == len(refs), "names must be unique"


def test_manifest_records_framework_and_optional_sha(tmp_path):
    m = _manifest(
        tmp_path,
        "repos:\n  - name: a\n    url: https://x/y\n    framework: crewai\n    sha: abc123\n",
    )
    ref = load_manifest(m)[0]
    assert ref.framework == "crewai"
    assert ref.sha == "abc123"


def test_missing_sha_defaults_to_empty(tmp_path):
    m = _manifest(tmp_path, "repos:\n  - name: a\n    url: https://x/y\n")
    assert load_manifest(m)[0].sha == ""


def test_empty_manifest_is_not_an_error(tmp_path):
    assert load_manifest(_manifest(tmp_path, "repos: []\n")) == []


def test_repo_ref_serializes_for_the_results_file():
    d = RepoRef(name="a", url="https://x/y", framework="crewai", sha="deadbeef").to_dict()
    assert d == {
        "name": "a",
        "url": "https://x/y",
        "framework": "crewai",
        "sha": "deadbeef",
        "demonstrative": False,
        "cohort": "original",
        "error": None,
    }

"""Corpus benchmark: discovery and deterministic checkers over real directory trees."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from spyv.bench.corpus import (
    format_corpus_report,
    grep_candidate_files,
    redact,
    run_corpus,
    run_repo,
)
from spyv.cli import main


@pytest.fixture()
def repo(tmp_path):
    """A small tree that exercises discovery, the grep baseline, and exposure."""
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "docs").mkdir()

    # discoverable by spyv AND by grep
    (root / "app" / "bot.py").write_text(
        'SYSTEM_PROMPT = "You are a helpful support agent. Answer order questions."\n',
        encoding="utf-8",
    )
    # a prompt carrying a credential -> deterministic checker hit
    (root / "app" / "leaky.py").write_text(
        'SYSTEM_PROMPT = "You are an admin bot. Use key sk-live-ABCDEFGHIJKLMNOP1234 for tools."\n',
        encoding="utf-8",
    )
    # prose that trips the naive baseline but is not a prompt
    (root / "docs" / "guide.md").write_text(
        "When you are a new contributor, read this first.\n", encoding="utf-8"
    )
    # noise that should be skipped entirely
    (root / "node_modules").mkdir()
    (root / "node_modules" / "x.py").write_text('SYSTEM_PROMPT = "You are a bot."\n', encoding="utf-8")
    return root


# --- redaction --------------------------------------------------------------


def test_redact_masks_the_middle_and_keeps_the_ends():
    out = redact("sk-live-ABCDEFGHIJKLMNOP1234")
    assert out.startswith("sk-l")
    assert out.endswith("1234")
    assert "ABCDEFGHIJ" not in out
    assert len(out) == len("sk-live-ABCDEFGHIJKLMNOP1234")


@pytest.mark.parametrize("value", ["", "a", "ab", "abcd"])
def test_redact_fully_masks_short_values(value):
    assert set(redact(value)) <= {"*"}


def test_redact_never_returns_the_input_for_a_real_secret():
    secret = "AKIA1234567890ABCD00"
    assert redact(secret) != secret


# --- grep baseline ----------------------------------------------------------


def test_grep_baseline_finds_prompt_markers_and_prose(repo):
    files = grep_candidate_files(repo)
    assert "app/bot.py" in files
    assert "docs/guide.md" in files, "the naive baseline is expected to over-trigger on prose"


def test_grep_baseline_skips_vendored_directories(repo):
    assert not any(f.startswith("node_modules/") for f in grep_candidate_files(repo))


def test_grep_baseline_on_empty_tree(tmp_path):
    assert grep_candidate_files(tmp_path) == set()


# --- single repo ------------------------------------------------------------


def test_run_repo_reports_yield_and_agreement(repo):
    r = run_repo(repo, name="demo")
    assert r.error is None
    assert r.name == "demo"
    assert r.prompts_found >= 2
    assert r.by_source_kind
    # guide.md is prose: grep fires, discovery does not
    assert "docs/guide.md" in r.grep_only
    assert r.both, "a real prompt should be found by both"


def test_run_repo_detects_a_credential_in_a_real_prompt(repo):
    r = run_repo(repo, name="demo")
    assert r.exposed_prompts >= 1
    assert any("secrets" in k for k in r.checker_hits)


def test_run_repo_redacts_evidence_by_default(repo):
    r = run_repo(repo, name="demo")
    blob = json.dumps(r.to_dict())
    assert "sk-live-ABCDEFGHIJKLMNOP1234" not in blob
    assert "*" in blob


def test_run_repo_reveals_only_when_asked(repo):
    r = run_repo(repo, name="demo", reveal=True)
    blob = json.dumps(r.to_dict())
    assert "sk-live-ABCDEFGHIJKLMNOP1234" in blob


def test_run_repo_records_a_missing_path_instead_of_raising(tmp_path):
    r = run_repo(tmp_path / "nope", name="ghost")
    assert r.error == "path not found"
    assert r.prompts_found == 0


# --- corpus aggregation -----------------------------------------------------


def test_run_corpus_aggregates_and_labels(repo, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.py").write_text(
        'SYSTEM_PROMPT = "You are a triage bot. Route each ticket to the right team."\n',
        encoding="utf-8",
    )

    res = run_corpus([repo, other], names=["one", "two"])
    assert [r["name"] for r in res["repos"]] == ["one", "two"]
    assert res["totals"]["repos_ok"] == 2
    assert res["totals"]["prompts_found"] >= 3
    assert res["reproducible"] is True
    assert res["evidence_redacted"] is True


def test_run_corpus_excludes_failed_repos_from_totals(repo, tmp_path):
    res = run_corpus([repo, tmp_path / "missing"])
    assert res["totals"]["repos"] == 2
    assert res["totals"]["repos_ok"] == 1


def test_corpus_agreement_partitions_are_disjoint(repo):
    r = run_repo(repo)
    assert not (r.both & r.spyv_only)
    assert not (r.both & r.grep_only)
    assert not (r.spyv_only & r.grep_only)


def test_format_corpus_report_mentions_the_redaction_stance(repo):
    text = format_corpus_report(run_corpus([repo]))
    assert "REDACTED" in text
    assert "grep" in text


def test_format_corpus_report_warns_when_unredacted(repo):
    text = format_corpus_report(run_corpus([repo], reveal=True))
    assert "UNREDACTED" in text


# --- CLI --------------------------------------------------------------------


def test_corpus_cli_runs_and_reports(repo):
    result = CliRunner().invoke(main, ["corpus", str(repo)])
    assert result.exit_code == 0, result.output
    assert "CORPUS BENCHMARK" in result.output


def test_corpus_cli_never_prints_a_secret(repo):
    result = CliRunner().invoke(main, ["corpus", str(repo), "--json"])
    assert result.exit_code == 0
    assert "sk-live-ABCDEFGHIJKLMNOP1234" not in result.output


def test_corpus_cli_reveal_requires_out(repo):
    result = CliRunner().invoke(main, ["corpus", str(repo), "--reveal"])
    assert result.exit_code == 2
    assert "--out" in result.output


def test_corpus_cli_reveal_writes_file_but_keeps_stdout_clean(repo, tmp_path):
    out = tmp_path / "findings.json"
    result = CliRunner().invoke(main, ["corpus", str(repo), "--reveal", "--out", str(out), "--json"])
    assert result.exit_code == 0, result.output
    assert "sk-live-ABCDEFGHIJKLMNOP1234" in out.read_text()
    assert "sk-live-ABCDEFGHIJKLMNOP1234" not in result.output


def test_corpus_cli_fail_on_exposure_trips(repo):
    result = CliRunner().invoke(main, ["corpus", str(repo), "--fail-on-exposure"])
    assert result.exit_code == 1


def test_corpus_cli_fail_on_exposure_passes_when_clean(tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.py").write_text(
        'SYSTEM_PROMPT = "You are a polite triage bot. Route each ticket to the right team."\n',
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, ["corpus", str(clean), "--fail-on-exposure"])
    assert result.exit_code == 0, result.output


def test_short_strings_are_below_the_discovery_precision_floor(tmp_path):
    """Discovery applies a 40-character floor so incidental strings are not counted.

    Documented as a test because the corpus benchmark's yield number depends on
    it: raising or lowering the floor moves every reported total.
    """
    root = tmp_path / "tiny"
    root.mkdir()
    (root / "a.py").write_text('SYSTEM_PROMPT = "You are a bot."\n', encoding="utf-8")
    assert run_repo(root).prompts_found == 0

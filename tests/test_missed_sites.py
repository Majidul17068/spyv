"""The missed-site audit's sampler and estimator.

The test that matters is the unbiasedness one. A weighted estimator that is
quietly wrong produces a confident number from real labels, which is worse than
producing none, so the planted-truth test fixes the arithmetic against a rate
nobody can argue with.
"""

from __future__ import annotations

from spyv.bench.missed_sites import (
    MISS_CAUSES,
    FileRecord,
    FoundSite,
    SampledFile,
    _read_source,
    draw_sample,
    estimate,
    frame_summary,
)


def frame(n_a: int = 100, n_b: int = 900, repos: int = 5) -> list[FileRecord]:
    out = []
    for i in range(n_a + n_b):
        out.append(FileRecord(
            repo=f"repo{i % repos}",
            path=f"pkg/mod{i}.py",
            stratum="production",
            lines=50,
            detected=1 if i < n_a else 0,
            parse_ok=True,
        ))
    return out


# ---------------------------------------------------------------------------
# frame
# ---------------------------------------------------------------------------
def test_arm_is_assigned_by_detection_not_by_content():
    detected = FileRecord("r", "a.py", "production", 10, 3, True)
    missed = FileRecord("r", "b.py", "production", 10, 0, True)
    assert detected.arm == "A"
    assert missed.arm == "B"


def test_unparseable_files_stay_in_the_frame():
    """A file the parser could not read is a file whose sites were all missed."""
    f = frame(n_a=2, n_b=2)
    f.append(FileRecord("r", "broken.py", "production", 5, 0, False, read_error="SyntaxError"))
    summary = frame_summary(f)
    assert summary["files"] == 5
    assert summary["unreadable"] == 1
    assert f[-1].arm == "B"


def test_source_is_decoded_the_way_python_decodes_it(tmp_path):
    """A BOM must not make a valid file look unparseable to the audit."""
    bom = tmp_path / "bom.py"
    bom.write_bytes(b"\xef\xbb\xbfx = 1\n")
    assert _read_source(bom) == "x = 1\n"

    cookie = tmp_path / "latin.py"
    cookie.write_bytes(b"# -*- coding: latin-1 -*-\ns = '\xe9'\n")
    assert "\xe9" in _read_source(cookie)


# ---------------------------------------------------------------------------
# sampling
# ---------------------------------------------------------------------------
def test_inclusion_probability_is_the_arm_sampling_fraction():
    sample = draw_sample(frame(), n_a=10, n_b=10)
    a = [f for f in sample if f.arm == "A"]
    b = [f for f in sample if f.arm == "B"]
    assert len(a) == len(b) == 10
    assert all(abs(f.inclusion_prob - 10 / 100) < 1e-12 for f in a)
    assert all(abs(f.inclusion_prob - 10 / 900) < 1e-12 for f in b)
    assert all(abs(f.weight - 1 / f.inclusion_prob) < 1e-9 for f in sample)


def test_the_draw_is_reproducible():
    a = draw_sample(frame(), n_a=15, n_b=15, seed=7)
    b = draw_sample(frame(), n_a=15, n_b=15, seed=7)
    assert [(x.repo, x.path) for x in a] == [(x.repo, x.path) for x in b]


def test_a_different_seed_draws_different_files():
    a = draw_sample(frame(), n_a=15, n_b=15, seed=7)
    b = draw_sample(frame(), n_a=15, n_b=15, seed=8)
    assert {x.path for x in a} != {x.path for x in b}


def test_asking_for_more_than_the_pool_holds_takes_the_pool():
    sample = draw_sample(frame(n_a=3, n_b=4), n_a=50, n_b=50)
    assert len(sample) == 7
    assert all(f.inclusion_prob == 1.0 for f in sample)


# ---------------------------------------------------------------------------
# estimation
# ---------------------------------------------------------------------------
def labelled(f: SampledFile, detected: int, missed: int) -> SampledFile:
    f.reviewed = True
    f.found = (
        [FoundSite(1, "c", "detected") for _ in range(detected)]
        + [FoundSite(2, "c", "missed", cause="unsupported_api") for _ in range(missed)]
    )
    f.no_instruction_text = not f.found
    return f


def test_weighted_rate_recovers_a_planted_truth():
    """Arm B is sampled 90x more thinly than arm A; the weights must undo that.

    Planted corpus: 100 arm-A files with one detected site each, 900 arm-B files
    with one missed site each. The true missed-site rate is 900/1000 = 90%. An
    unweighted count over an equal-sized sample would report 50%.
    """
    sample = draw_sample(frame(n_a=100, n_b=900), n_a=20, n_b=20)
    for f in sample:
        labelled(f, detected=1, missed=0) if f.arm == "A" else labelled(f, detected=0, missed=1)

    result = estimate(sample)
    assert abs(result["missed_site_rate"] - 0.9) < 1e-9

    naive = sum(f.missed for f in sample) / sum(f.sites for f in sample)
    assert abs(naive - 0.5) < 1e-9  # what ignoring the weights would have said


def test_unreviewed_files_are_counted_but_not_estimated_over():
    sample = draw_sample(frame(), n_a=10, n_b=10)
    for f in sample[:5]:
        labelled(f, detected=1, missed=1)
    result = estimate(sample)
    assert result["reviewed"] == 5
    assert result["unreviewed"] == 15


def test_nothing_reviewed_yields_no_estimate():
    result = estimate(draw_sample(frame(), n_a=5, n_b=5))
    assert "missed_site_rate" not in result
    assert "nothing to estimate" in result["note"]


def test_uncertain_labels_are_reported_not_resolved():
    sample = draw_sample(frame(), n_a=4, n_b=4)
    for f in sample:
        f.reviewed = True
        f.found = [FoundSite(1, "c", "missed", cause="alias", confidence="uncertain")]
    assert estimate(sample)["uncertain_labels"] == 8


def test_ai_assisted_labels_raise_a_warning():
    sample = draw_sample(frame(), n_a=4, n_b=4)
    for f in sample:
        labelled(f, detected=1, missed=0)
    sample[0].label_source = "ai_assisted"
    result = estimate(sample)
    assert result["ai_assisted"] == 1
    assert "not independent human ground truth" in result["warning"]


def test_causes_are_broken_down_and_come_from_the_fixed_vocabulary():
    sample = draw_sample(frame(), n_a=6, n_b=6)
    for i, f in enumerate(sample):
        f.reviewed = True
        f.found = [FoundSite(1, "c", "missed", cause="alias" if i % 2 else "config_driven")]
    causes = estimate(sample)["by_cause"]
    assert set(causes) <= MISS_CAUSES
    assert sum(causes.values()) == 12


def test_interval_is_reported_and_brackets_the_estimate():
    sample = draw_sample(frame(), n_a=20, n_b=20)
    for i, f in enumerate(sample):
        labelled(f, detected=1, missed=i % 3 == 0)
    result = estimate(sample)
    lo, hi = result["missed_site_rate_ci95"]
    assert 0.0 <= lo <= result["missed_site_rate"] <= hi <= 1.0


def test_files_with_no_instruction_text_still_carry_weight():
    """An empty file is an observation, not missing data."""
    sample = draw_sample(frame(), n_a=10, n_b=10)
    for f in sample:
        labelled(f, detected=0, missed=0)
    result = estimate(sample)
    assert result["reviewed"] == 20
    assert result["missed_site_rate"] == 0.0


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------
def test_sample_round_trips_through_disk(tmp_path):
    """Weights are meaningless without the probabilities, so they must survive."""
    from spyv.bench.missed_sites import load, save

    sample = draw_sample(frame(), n_a=5, n_b=5)
    labelled(sample[0], detected=1, missed=2)
    sample[0].found[1].confidence = "uncertain"
    path = tmp_path / "files.json"
    save(sample, path, meta={"frame_A": 100, "frame_B": 900})

    back, meta = load(path)
    assert meta["frame_B"] == 900
    assert [f.inclusion_prob for f in back] == [f.inclusion_prob for f in sample]
    assert back[0].found[1].confidence == "uncertain"
    assert estimate(back)["missed_site_rate"] == estimate(sample)["missed_site_rate"]

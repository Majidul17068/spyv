"""Sampling, persistence and scoring for human validation."""

from __future__ import annotations

import pytest

from spyv.bench.annotate import Item, cohens_kappa, load, save, score


def _item(pred="static", true=None, is_site=None, construct="Task.description", line=1):
    return Item(repo="r", file="a.py", line=line, construct=construct, framework="crewai",
                predicted_visibility=pred, is_prompt_site=is_site, true_visibility=true)


# --- kappa ------------------------------------------------------------------


def test_perfect_agreement_is_one():
    assert cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == pytest.approx(1.0)


def test_chance_level_agreement_is_near_zero():
    a = ["a", "b"] * 20
    b = ["a", "a", "b", "b"] * 10
    assert abs(cohens_kappa(a, b)) < 0.25


def test_kappa_corrects_for_chance_not_just_raw_agreement():
    """The property that makes kappa worth computing.

    Both annotators say "yes" 90% of the time and agree on 82 of 100 items.
    Raw agreement of 82% sounds strong, but two annotators with those marginals
    would agree 82% of the time by chance alone, so kappa is zero.
    """
    # a: y on 0-89, n on 90-99
    a = ["y"] * 90 + ["n"] * 10
    # b: disagrees on 9 of a's y-items and 9 of a's n-items, keeping 90/10 marginals
    b = ["y"] * 81 + ["n"] * 9 + ["y"] * 9 + ["n"] * 1
    assert sum(1 for x, y in zip(a, b, strict=False) if x == y) == 82
    assert b.count("y") == 90
    assert cohens_kappa(a, b) == pytest.approx(0.0, abs=1e-9)


def test_kappa_on_mismatched_or_empty_input():
    assert cohens_kappa([], []) == 0.0
    assert cohens_kappa(["a"], ["a", "b"]) == 0.0


def test_kappa_when_one_class_is_universal():
    assert cohens_kappa(["y"] * 10, ["y"] * 10) == pytest.approx(1.0)


# --- scoring ----------------------------------------------------------------


def test_site_precision_counts_confirmed_over_labelled():
    items = [_item(is_site=True, true="static", line=i) for i in range(8)]
    items += [_item(is_site=False, line=i + 100) for i in range(2)]
    r = score(items)
    assert r["labelled"] == 10
    assert r["site_precision"] == pytest.approx(0.8)


def test_visibility_accuracy_only_counts_real_sites():
    items = [_item(pred="static", true="static", is_site=True, line=1),
             _item(pred="static", true="partial", is_site=True, line=2),
             _item(pred="opaque", is_site=False, line=3)]
    r = score(items)
    assert r["visibility_accuracy"] == pytest.approx(0.5)


def test_unlabelled_items_are_excluded():
    r = score([_item(is_site=True, true="static"), _item()])
    assert r["labelled"] == 1


def test_no_labels_is_not_an_error():
    assert score([_item(), _item()])["labelled"] == 0


def test_recall_is_reported_as_not_estimable():
    """Precision must not be passed off as recall: this sample frame is a sample
    of detections, so it cannot find sites the detector missed."""
    r = score([_item(is_site=True, true="static")])
    assert r["recall"] is None
    assert "recall" in r["recall_note"].lower()


def test_single_annotator_reports_no_kappa_and_says_why():
    r = score([_item(is_site=True, true="static")])
    assert r["annotators"] == 1
    assert r["kappa"] is None
    assert "two annotators" in r["kappa_note"]


def test_two_passes_produce_a_kappa_and_a_provenance_caveat():
    a = [_item(is_site=True, true="static", line=i) for i in range(10)]
    b = [_item(is_site=True, true="static", line=i) for i in range(10)]
    r = score(a, b)
    assert r["annotators"] == 2
    assert r["kappa"] == pytest.approx(1.0)
    assert r["n_paired"] == 10
    assert "intra-rater" in r["kappa_note"]


def test_pairing_matches_on_site_identity_not_order():
    a = [_item(is_site=True, true="static", line=1), _item(is_site=True, true="static", line=2)]
    b = [_item(is_site=True, true="static", line=2), _item(is_site=True, true="partial", line=1)]
    r = score(a, b)
    assert r["n_paired"] == 2
    assert r["kappa_visibility"] < 1.0


def test_confusion_matrix_records_direction():
    r = score([_item(pred="opaque", true="static", is_site=True)])
    assert "opaque->static" in r["confusion_predicted_vs_true"]


def test_per_construct_breakdown():
    items = [_item(construct="Task.description", is_site=True, true="static", line=1),
             _item(construct="const.prompt", is_site=False, line=2)]
    bc = score(items)["by_construct"]
    assert bc["Task.description"]["true"] == 1
    assert bc["const.prompt"]["true"] == 0


# --- persistence ------------------------------------------------------------


def test_round_trip_preserves_labels(tmp_path):
    p = tmp_path / "l.json"
    save([_item(is_site=True, true="partial")], p, {"sample_size": 1})
    items, meta = load(p)
    assert items[0].is_prompt_site is True
    assert items[0].true_visibility == "partial"
    assert meta["sample_size"] == 1


def test_labelled_property():
    assert not _item().labelled
    assert _item(is_site=False).labelled

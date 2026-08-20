"""Offline tests for the benchmark harness (deterministic tier, no API key)."""
from __future__ import annotations

from spyv.bench import DATASET_DEFAULT, load_dataset, run_benchmark
from spyv.bench.harness import prf, run_deterministic_tier, wilson


def test_prf_math():
    p, r, f1 = prf(tp=3, fp=1, fn=1)
    assert round(p, 3) == 0.75
    assert round(r, 3) == 0.75
    assert round(f1, 3) == 0.75
    assert prf(0, 0, 0) == (0.0, 0.0, 0.0)


def test_wilson_bounds():
    lo, hi = wilson(2, 2)
    assert 0.0 <= lo <= hi <= 1.0
    assert wilson(0, 0) == (0.0, 0.0)
    # a perfect small sample must NOT report a tight interval
    lo, hi = wilson(2, 2)
    assert lo < 0.9  # honest wide CI at N=2


def test_seed_dataset_wellformed():
    cases = load_dataset(DATASET_DEFAULT)
    assert len(cases) >= 10
    for c in cases:
        assert c["label"] in ("vulnerable", "safe")
        assert c["system_prompt"].strip()
        if c["label"] == "safe":
            assert not c.get("deterministic_detectable", False)


def test_deterministic_tier_catches_embedded_secrets():
    cases = load_dataset(DATASET_DEFAULT)
    res = run_deterministic_tier(cases)
    m = res.metrics
    # every embedded secret/PII case is caught; no safe prompt fires a checker
    assert m["fn"] == 0, "a deterministic-detectable case was missed"
    assert m["fp"] == 0, "a checker fired on a safe prompt"
    assert m["tp"] >= 2
    assert m["reproducible"] is True


def test_run_benchmark_deterministic_offline():
    results = run_benchmark(tier="deterministic")
    assert results["n_cases"] == results["n_vulnerable"] + results["n_safe"]
    det = results["tiers"]["deterministic"]["metrics"]
    assert det["fn"] == 0
    assert "llm_judge" not in results["tiers"]  # no LLM call in this tier


def test_deterministic_is_reproducible():
    a = run_benchmark(tier="deterministic")["tiers"]["deterministic"]["metrics"]
    b = run_benchmark(tier="deterministic")["tiers"]["deterministic"]["metrics"]
    assert a == b  # byte-identical across runs

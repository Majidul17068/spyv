"""Spyv benchmark (v0.4.0 Measurement Release).

Public API:
    from spyv.bench import run_benchmark, format_report, load_dataset

CLI:
    python -m spyv.bench                 # deterministic tier, no key, reproducible
    python -m spyv.bench --tier llm --provider openai --model gpt-4o
    spyv bench --tier all --model gpt-4o
    spyv corpus ../some-repo ../another-repo   # real code, no key
"""
from __future__ import annotations

from .corpus import format_corpus_report, run_corpus, run_repo
from .harness import (
    DATASET_DEFAULT,
    format_report,
    load_dataset,
    run_benchmark,
    run_deterministic_tier,
    run_llm_tier,
    run_redteam_tier,
)

__all__ = [
    "DATASET_DEFAULT",
    "format_corpus_report",
    "format_report",
    "load_dataset",
    "run_benchmark",
    "run_corpus",
    "run_deterministic_tier",
    "run_llm_tier",
    "run_redteam_tier",
    "run_repo",
]

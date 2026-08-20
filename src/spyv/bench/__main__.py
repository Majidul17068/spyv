"""`python -m spyv.bench` entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .harness import format_report, run_benchmark


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spyv.bench", description="Spyv benchmark harness")
    ap.add_argument("--dataset", type=Path, default=None, help="labeled dataset YAML (default: seed.yaml)")
    ap.add_argument("--tier", choices=["deterministic", "llm", "all"], default="deterministic",
                    help="deterministic (no key) | llm | all (adds redteam)")
    ap.add_argument("--provider", default="auto", help="LLM provider (auto/openai/anthropic/gemini/...)")
    ap.add_argument("--model", default=None, help="model name")
    ap.add_argument("--base-url", default=None, help="base URL for local/compatible endpoints")
    ap.add_argument("--repeat", type=int, default=1, help="repeat each case K times (consistency)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of the pretty report")
    ap.add_argument("--out", type=Path, default=None, help="write full JSON results to this path")
    args = ap.parse_args(argv)

    try:
        results = run_benchmark(
            dataset_path=args.dataset,
            tier=args.tier,
            provider_name=args.provider,
            model=args.model,
            base_url=args.base_url,
            repeat=args.repeat,
            out=args.out,
        )
    except Exception as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        import json
        print(json.dumps(results, indent=2))
    else:
        print(format_report(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

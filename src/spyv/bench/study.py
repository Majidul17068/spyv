"""Driver for the prompt-surface study: fetch, measure, aggregate, emit.

Every figure in the paper comes from here. Previously the aggregation existed
only as ad-hoc scripts, so a reader could re-execute the analysers but could not
regenerate the result files or check the interval arithmetic. Reviewers were
right that this under-delivered on the artifact's own availability claim.

    python -m spyv.bench.study            # all three research questions
    python -m spyv.bench.study --rq 1     # just recoverability
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics as st
from collections import Counter
from pathlib import Path
from typing import Any

RESULTS = Path(__file__).parent / "results"
BOOTSTRAP_DRAWS = 20000
BOOTSTRAP_SEED = 20260826


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def cluster_bootstrap(values: list[float], stat: Any, draws: int = BOOTSTRAP_DRAWS) -> tuple[float, float]:
    """Resample repositories, not sites: the repository is the clustering unit."""
    rng = random.Random(BOOTSTRAP_SEED)
    out = sorted(stat([rng.choice(values) for _ in values]) for _ in range(draws))
    return out[int(0.025 * draws)], out[int(0.975 * draws)]


def design_effect(rates: list[float], sizes: list[int]) -> dict[str, float]:
    """Intraclass correlation and the effective sample it implies.

    Treating sites as independent draws understates every interval, because
    recoverability varies far more between repositories than a binomial model
    allows. This quantifies by how much.
    """
    n_total = sum(sizes)
    k_repos = len(sizes)
    p_bar = sum(r * m for r, m in zip(rates, sizes, strict=False)) / n_total
    m_bar = n_total / k_repos
    msb = sum(m * (r - p_bar) ** 2 for r, m in zip(rates, sizes, strict=False)) / (k_repos - 1)
    msw = sum(m * r * (1 - r) for r, m in zip(rates, sizes, strict=False)) / (n_total - k_repos)
    icc = (msb - msw) / (msb + (m_bar - 1) * msw)
    deff = 1 + (m_bar - 1) * icc
    return {"icc": icc, "mean_cluster_size": m_bar, "design_effect": deff, "effective_n": n_total / deff}


def _repos() -> list[tuple[str, Path, str]]:
    from .fetch import DEFAULT_CACHE, load_manifest

    out = []
    for ref in load_manifest():
        path = DEFAULT_CACHE / ref.name
        if path.exists():
            out.append((ref.name, path, ref.sha))
    return out


def run_rq1() -> dict[str, Any]:
    from .visibility import run_visibility

    rows = []
    for name, path, sha in _repos():
        m = run_visibility(path, name=name).metrics()
        if not m["sites"]:
            continue
        rows.append({"name": name, "sha": sha, **{k: m[k] for k in
                    ("sites", "static", "partial", "opaque", "spv_full", "spv_partial")},
                     "files": run_visibility(path, name=name).files_scanned,
                     "by_construct": m["by_construct"]})
    rates = [r["spv_partial"] for r in rows]
    sizes = [r["sites"] for r in rows]
    k = sum(r["static"] + r["partial"] for r in rows)
    n = sum(sizes)
    de = design_effect(rates, sizes)
    return {
        "rq": 1,
        "totals": {"repos": len(rows), "sites": n, "recoverable": k,
                   "static": sum(r["static"] for r in rows),
                   "partial": sum(r["partial"] for r in rows),
                   "opaque": sum(r["opaque"] for r in rows),
                   "spv_partial_pooled": k / n},
        "clustered_by_repo": {
            "mean": st.mean(rates), "mean_ci95": cluster_bootstrap(rates, st.mean),
            "median": st.median(rates), "median_ci95": cluster_bootstrap(rates, st.median),
            "min": min(rates), "max": max(rates), "stdev": st.stdev(rates),
        },
        "pooled_ci95_naive": wilson(k, n),
        "pooled_ci95_design_adjusted": wilson(round((k / n) * de["effective_n"]), round(de["effective_n"])),
        "clustering": de,
        "repos": rows,
    }


def run_rq2() -> dict[str, Any]:
    from .headroom import run_headroom_project

    buckets: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    rows = []
    for name, path, sha in _repos():
        h = run_headroom_project(path, name=name)
        if not h["opaque_sites"]:
            continue
        buckets.update(h["buckets"])
        reasons.update(h["details"])
        rows.append({"name": name, "sha": sha, "opaque_sites": h["opaque_sites"], "buckets": h["buckets"]})
    total = sum(buckets.values())
    return {
        "rq": 2,
        "opaque_sites": total,
        "buckets": dict(buckets),
        "shares": {k: v / total for k, v in buckets.items()},
        "ci95": {k: wilson(v, total) for k, v in buckets.items()},
        "note": ("runtime_bound is classifier output, not a bound: most of it rests on an "
                 "identifier heuristic or an unconditional subscript rule rather than on "
                 "evidence from reading a callee. See METRICS.md and the paper's Section V."),
        "reasons_top": dict(reasons.most_common(25)),
        "repos": rows,
    }


def run_rq3() -> dict[str, Any]:
    from .content import analyze_sites
    from .visibility import run_visibility

    rows = []
    agg = Counter()
    sec_cls: Counter[str] = Counter()
    pii_cls: Counter[str] = Counter()
    for name, path, sha in _repos():
        sites = run_visibility(path, name=name).sites
        m = analyze_sites(sites, name=name).metrics()
        if not m["recoverable_prompts"]:
            continue
        sec_cls.update(m["m1_secrets"]["classes"])
        pii_cls.update(m["m2_pii"]["classes"])
        agg["recoverable"] += m["recoverable_prompts"]
        agg["m1"] += m["m1_secrets"]["prompts_with_plausible"]
        agg["m2"] += m["m2_pii"]["prompts_with_plausible"]
        agg["m3"] += m["m3_interpolation"]["prompts"]
        rows.append({"name": name, "sha": sha, "recoverable_prompts": m["recoverable_prompts"],
                     "m1_plausible": m["m1_secrets"]["prompts_with_plausible"],
                     "m2_plausible": m["m2_pii"]["prompts_with_plausible"],
                     "m3_interpolating": m["m3_interpolation"]["prompts"]})
    n = agg["recoverable"]
    return {
        "rq": 3,
        "recoverable_prompts": n,
        "m1_credentials": {"prompts": agg["m1"], "rate": agg["m1"] / n, "ci95": wilson(agg["m1"], n),
                           "hit_classes": dict(sec_cls),
                           "note": "no credential-shaped match of any class occurred; the "
                                   "classification apparatus was never exercised for M1."},
        "m2_personal_data": {"prompts": agg["m2"], "rate": agg["m2"] / n, "ci95": wilson(agg["m2"], n),
                             "hit_classes": dict(pii_cls)},
        "m3_interpolation": {"prompts": agg["m3"], "rate": agg["m3"] / n, "ci95": wilson(agg["m3"], n)},
        "m4_guardrails": {"withdrawn": True,
                          "note": "keyword families were wrong in both directions; no rate is reported."},
        "repos": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spyv.bench.study")
    ap.add_argument("--rq", type=int, choices=[1, 2, 3], default=None)
    ap.add_argument("--out", type=Path, default=RESULTS)
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    wanted = [args.rq] if args.rq else [1, 2, 3]
    for rq, fn, name in ((1, run_rq1, "rq1_visibility"), (2, run_rq2, "rq2_headroom"), (3, run_rq3, "rq3_content")):
        if rq not in wanted:
            continue
        print(f"running RQ{rq} ...", flush=True)
        data = fn()
        path = args.out / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

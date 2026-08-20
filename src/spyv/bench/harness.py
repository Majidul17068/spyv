"""Spyv benchmark harness (v0.4.0 Measurement Release).

Measures spyv against a labeled dataset and reports:
  * DETERMINISTIC tier  — pure regex checkers, no LLM, fully reproducible (runs
                          offline with no API key; the CI-safe portion).
  * LLM-JUDGE tier      — analyze(); precision / recall / F1, per-OWASP recall,
                          confusion matrix, and (with --repeat) consistency.
  * RED-TEAM tier       — redteam(); detection rate on known-exploitable cases.

The two accuracy tiers are reported SEPARATELY on purpose (see
SPYV-VERDICT-AND-PLAN T5): deterministic findings are ground truth; the LLM
judge is an advisory layer whose error must be bounded and disclosed, never
blended into one headline number.

A benchmark MEASURES; it does not IMPROVE. This seed set is self-authored and
small — a smoke test / regression guard, not a publishable claim. Real numbers
need external, held-out labels and a larger N.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATASET_DEFAULT = Path(__file__).parent / "dataset" / "seed.yaml"
BASELINE_DEFAULT = Path(__file__).parent / "baseline.json"


# --------------------------------------------------------------------------
# dataset
# --------------------------------------------------------------------------
def load_dataset(path: Path) -> list[dict[str, Any]]:
    import yaml  # spyv already depends on pyyaml for the CLI

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = data.get("cases", []) if isinstance(data, dict) else []
    if not cases:
        raise ValueError(f"No cases found in dataset {path}")
    return cases


# --------------------------------------------------------------------------
# metric helpers
# --------------------------------------------------------------------------
def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _norm_owasp(tag: str | None) -> str:
    return (tag or "").strip().upper().replace(" ", "")


# --------------------------------------------------------------------------
# tiers
# --------------------------------------------------------------------------
@dataclass
class TierResult:
    name: str
    per_case: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def run_deterministic_tier(cases: list[dict[str, Any]]) -> TierResult:
    """Pure regex checkers on the prompt text. No LLM, fully reproducible.

    Positives = cases marked `deterministic_detectable: true` (embedded
    secret/PII). We scan the PROMPT as if it were output text, so an embedded
    key/PII fires check_secrets / check_pii.
    """
    from ..checkers import run_checkers

    res = TierResult(name="deterministic")
    tp = fp = fn = tn = 0
    for c in cases:
        hits = run_checkers("", c["system_prompt"])
        fired = len(hits) > 0
        should = bool(c.get("deterministic_detectable", False))
        if fired and should:
            tp += 1
        elif fired and not should:
            fp += 1
        elif (not fired) and should:
            fn += 1
        else:
            tn += 1
        res.per_case.append({
            "id": c["id"], "should_detect": should, "fired": fired,
            "hits": [f"{h.checker}/{h.label}" for h in hits],
        })
    p, r, f1 = prf(tp, fp, fn)
    n_pos = tp + fn
    res.metrics = {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": p, "recall": r, "f1": f1,
        "recall_ci95": wilson(tp, n_pos) if n_pos else (0.0, 0.0),
        "n_positives": n_pos, "n": len(cases),
        "reproducible": True,
    }
    return res


def run_llm_tier(cases: list[dict[str, Any]], llm: Any, model: str, repeat: int = 1) -> TierResult:
    """analyze() on each case. Binary rule: predicted_vulnerable = verdict != 'ship'.

    'ship' is spyv's own "good to deploy" verdict, so treating anything else as
    a flagged vulnerability matches the tool's semantics.
    """
    from ..reason import analyze

    res = TierResult(name="llm_judge")
    tp = fp = fn = tn = 0
    owasp_expected: dict[str, int] = {}
    owasp_hit: dict[str, int] = {}
    verdict_stable = 0
    score_stds: list[float] = []

    for c in cases:
        verdicts: list[str] = []
        scores: list[float] = []
        found_tags: set[str] = set()
        for _ in range(max(1, repeat)):
            rep = analyze(
                system_prompt=c["system_prompt"],
                llm=llm,
                model=model,
                tools=None,  # names only in dataset; analyze takes callables/dicts
            )
            verdicts.append(rep.overall_verdict)
            scores.append(rep.overall_score)
            for v in rep.vulnerabilities:
                found_tags.add(_norm_owasp(v.owasp_llm_tag))

        verdict = statistics.mode(verdicts)
        predicted_vuln = verdict != "ship"
        is_vuln = c["label"] == "vulnerable"
        if predicted_vuln and is_vuln:
            tp += 1
        elif predicted_vuln and not is_vuln:
            fp += 1
        elif (not predicted_vuln) and is_vuln:
            fn += 1
        else:
            tn += 1

        # per-OWASP recall (only meaningful on vulnerable cases)
        for tag in c.get("expected_owasp", []) or []:
            t = _norm_owasp(tag)
            owasp_expected[t] = owasp_expected.get(t, 0) + 1
            if t in found_tags:
                owasp_hit[t] = owasp_hit.get(t, 0) + 1

        if repeat > 1:
            verdict_stable += int(len(set(verdicts)) == 1)
            score_stds.append(statistics.pstdev(scores) if len(scores) > 1 else 0.0)

        res.per_case.append({
            "id": c["id"], "label": c["label"], "verdict": verdict,
            "verdicts_all": verdicts, "scores": scores,
            "predicted_vulnerable": predicted_vuln,
            "found_owasp": sorted(t for t in found_tags if t),
            "expected_owasp": [_norm_owasp(t) for t in (c.get("expected_owasp") or [])],
        })

    p, r, f1 = prf(tp, fp, fn)
    n = len(cases)
    res.metrics = {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": p, "recall": r, "f1": f1,
        "precision_ci95": wilson(tp, tp + fp),
        "recall_ci95": wilson(tp, tp + fn),
        "n": n, "decision_rule": "predicted_vulnerable = overall_verdict != 'ship'",
        "per_owasp_recall": {
            t: {"hit": owasp_hit.get(t, 0), "expected": owasp_expected[t]}
            for t in sorted(owasp_expected)
        },
        "reproducible": False,
    }
    if repeat > 1:
        res.metrics["consistency"] = {
            "repeat": repeat,
            "verdict_stable_cases": verdict_stable,
            "verdict_stability_rate": verdict_stable / n if n else 0.0,
            "mean_score_stddev": statistics.mean(score_stds) if score_stds else 0.0,
        }
    return res


def run_redteam_tier(cases: list[dict[str, Any]], llm: Any, model: str) -> TierResult:
    """redteam() detection rate on cases marked redteam_exploitable."""
    from ..redteam import redteam

    res = TierResult(name="redteam")
    exploitable = [c for c in cases if c.get("redteam_exploitable")]
    breached_cases = 0
    for c in exploitable:
        report = redteam(system_prompt=c["system_prompt"], llm=llm, model=model)
        did = report.breached > 0
        breached_cases += int(did)
        res.per_case.append({
            "id": c["id"], "breached": did,
            "n_breached_attacks": report.breached, "n_attacks": report.total,
        })
    n = len(exploitable)
    res.metrics = {
        "exploitable_cases": n,
        "cases_breached": breached_cases,
        "detection_rate": breached_cases / n if n else 0.0,
        "detection_rate_ci95": wilson(breached_cases, n),
        "reproducible": False,
    }
    return res


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def run_benchmark(
    *,
    dataset_path: Path | None = None,
    tier: str = "deterministic",
    provider_name: str = "auto",
    model: str | None = None,
    base_url: str | None = None,
    repeat: int = 1,
    out: Path | None = None,
) -> dict[str, Any]:
    cases = load_dataset(dataset_path or DATASET_DEFAULT)
    results: dict[str, Any] = {
        "dataset": str(dataset_path or DATASET_DEFAULT),
        "n_cases": len(cases),
        "n_vulnerable": sum(c["label"] == "vulnerable" for c in cases),
        "n_safe": sum(c["label"] == "safe" for c in cases),
        "tier": tier,
        "tiers": {},
    }

    # deterministic tier always runs — it needs no key and is the reproducible floor.
    det = run_deterministic_tier(cases)
    results["tiers"]["deterministic"] = {"metrics": det.metrics, "per_case": det.per_case}

    if tier in ("llm", "all"):
        llm = _make_llm(provider_name, model, base_url)
        resolved_model = model or _default_model(provider_name)
        llm_res = run_llm_tier(cases, llm, resolved_model, repeat=repeat)
        results["tiers"]["llm_judge"] = {"metrics": llm_res.metrics, "per_case": llm_res.per_case}
        if tier == "all":
            rt = run_redteam_tier(cases, llm, resolved_model)
            results["tiers"]["redteam"] = {"metrics": rt.metrics, "per_case": rt.per_case}
        results["model_used"] = resolved_model

    if out:
        Path(out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        results["_written_to"] = str(out)
    return results


def _default_model(provider_name: str) -> str:
    from ..providers.factory import _DEFAULT_MODELS

    return _DEFAULT_MODELS.get(provider_name, "gpt-4o")


def _make_llm(provider_name: str, model: str | None, base_url: str | None) -> Any:
    from ..providers import auto, provider

    if provider_name == "auto":
        return auto(model=model)
    return provider(provider_name, model=model, base_url=base_url)


# --------------------------------------------------------------------------
# pretty printing
# --------------------------------------------------------------------------
def format_report(results: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 68)
    lines.append("SPYV BENCHMARK  (v0.4.0 Measurement Release)")
    lines.append("=" * 68)
    lines.append(
        f"dataset: {results['dataset']}   "
        f"cases: {results['n_cases']}  (vulnerable {results['n_vulnerable']} / safe {results['n_safe']})"
    )
    lines.append("")

    det = results["tiers"]["deterministic"]["metrics"]
    lo, hi = det["recall_ci95"]
    lines.append("-- DETERMINISTIC tier (regex, no LLM, reproducible) " + "-" * 16)
    lines.append(
        f"   positives (embedded secret/PII): {det['n_positives']}   "
        f"precision {det['precision']*100:.0f}%   recall {det['recall']*100:.0f}%  "
        f"(95% CI {lo*100:.0f}-{hi*100:.0f}%)   F1 {det['f1']:.2f}"
    )
    lines.append(f"   confusion: TP {det['tp']}  FP {det['fp']}  FN {det['fn']}  TN {det['tn']}")

    if "llm_judge" in results["tiers"]:
        m = results["tiers"]["llm_judge"]["metrics"]
        plo, phi = m["precision_ci95"]
        rlo, rhi = m["recall_ci95"]
        lines.append("")
        lines.append("-- LLM-JUDGE tier (advisory, NOT reproducible) " + "-" * 20)
        lines.append(f"   rule: {m['decision_rule']}")
        lines.append(
            f"   precision {m['precision']*100:.0f}% (95% CI {plo*100:.0f}-{phi*100:.0f}%)   "
            f"recall {m['recall']*100:.0f}% (95% CI {rlo*100:.0f}-{rhi*100:.0f}%)   F1 {m['f1']:.2f}"
        )
        lines.append(f"   confusion: TP {m['tp']}  FP {m['fp']}  FN {m['fn']}  TN {m['tn']}")
        if m["per_owasp_recall"]:
            parts = [f"{t} {d['hit']}/{d['expected']}" for t, d in m["per_owasp_recall"].items()]
            lines.append("   per-OWASP recall: " + "  ".join(parts))
        if "consistency" in m:
            c = m["consistency"]
            lines.append(
                f"   consistency (repeat {c['repeat']}): verdict-stable "
                f"{c['verdict_stable_cases']}/{results['n_cases']} "
                f"({c['verdict_stability_rate']*100:.0f}%)   "
                f"mean score sd {c['mean_score_stddev']:.2f}"
            )

    if "redteam" in results["tiers"]:
        rt = results["tiers"]["redteam"]["metrics"]
        lo, hi = rt["detection_rate_ci95"]
        lines.append("")
        lines.append("-- RED-TEAM tier (live attacks) " + "-" * 35)
        lines.append(
            f"   detection rate on exploitable cases: {rt['cases_breached']}/{rt['exploitable_cases']} "
            f"({rt['detection_rate']*100:.0f}%, 95% CI {lo*100:.0f}-{hi*100:.0f}%)"
        )

    lines.append("")
    lines.append("NOTE: self-authored SEED set — a smoke test / regression guard, not a")
    lines.append("publishable number. Deterministic accuracy is reported separately from the")
    lines.append("LLM-judge accuracy on purpose. For a real claim: external/held-out labels,")
    lines.append("larger N, reported CIs (see SPYV-VERDICT-AND-PLAN T5).")
    return "\n".join(lines)


__all__ = [
    "DATASET_DEFAULT",
    "format_report",
    "load_dataset",
    "prf",
    "run_benchmark",
    "run_deterministic_tier",
    "run_llm_tier",
    "run_redteam_tier",
    "wilson",
]

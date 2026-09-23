"""Frozen corrective measurement. Run as python -m spyv.bench.corrective_study."""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import platform
import random
import statistics
import subprocess
import time
import tokenize
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml

from spyv.bench.scaffolding import SCAFFOLD_DIRS
from spyv.bench.visibility import sites_in_source
from spyv.discovery import _SKIP_DIRS

SEED = 20260910
DRAWS = 10000


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(s):
    return (s.file, s.line, s.construct, s.call_line, s.call_col, s.call_end_line, s.call_end_col)


def stratum(path, demo, scripts=True):
    p = PurePosixPath(path)
    dirs = SCAFFOLD_DIRS if scripts else SCAFFOLD_DIRS - {"scripts"}
    marked = any(x.lower() in dirs for x in p.parts[:-1])
    name = p.name.lower()
    marked |= name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py")
    return "scaffolding" if demo or marked else "other"


def describe(counts):
    counts = {k: counts.get(k, 0) for k in ("static", "partial", "opaque")}
    n = sum(counts.values())
    return {**counts, "n": n, "yield": (counts["static"] + counts["partial"]) / n if n else None}


def interval(values, estimator=statistics.median):
    if not values:
        return None
    rng = random.Random(SEED)
    draws = sorted(estimator(rng.choices(values, k=len(values))) for _ in range(DRAWS))
    return [draws[int(0.025 * DRAWS)], draws[int(0.975 * DRAWS) - 1]]


def summarize(repos):
    result = {}
    for cohort in ("all", "original", "expansion"):
        selected = [r for r in repos if cohort == "all" or r["cohort"] == cohort]
        group = {}
        keys = sorted({k for r in selected for k in r["counts"]})
        for key in keys:
            rows = [describe(r["counts"].get(key, {})) for r in selected]
            values = [r["yield"] for r in rows if r["n"]]
            pooled = Counter()
            for r in rows:
                pooled.update({k: r[k] for k in ("static", "partial", "opaque")})
            group[key] = {
                **describe(pooled),
                "nonempty_repos": len(values),
                "median": statistics.median(values) if values else None,
                "median_ci95": interval(values),
            }
        for unit in ("all", "use", "definition"):
            deltas = []
            for r in selected:
                a = describe(r["counts"].get("scoped/" + unit + "/all", {}))
                b = describe(r["counts"].get("literal/" + unit + "/all", {}))
                if a["n"]:
                    deltas.append(a["yield"] - b["yield"])
            group["paired_gain/" + unit] = {
                "n": len(deltas),
                "mean": statistics.mean(deltas) if deltas else None,
                "mean_ci95": interval(deltas, statistics.mean),
            }
        result[cohort] = group
    return result


def run(cache, out, manifest):
    out.mkdir(parents=True, exist_ok=False)
    toolroot = Path(__file__).resolve().parents[3]
    started = datetime.now(timezone.utc).isoformat()
    manifest_bytes = manifest.read_bytes()
    entries = yaml.safe_load(manifest_bytes)["repos"]
    metadata = {
        "started_utc": started,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "code_commit": git(toolroot, "rev-parse", "HEAD").decode().strip(),
        "code_status": git(toolroot, "status", "--porcelain").decode(),
        "source_sha256": {
            str(p.relative_to(toolroot)): digest(p.read_bytes())
            for p in (
                Path(__file__),
                toolroot / "src/spyv/bindings.py",
                toolroot / "src/spyv/bench/visibility.py",
                toolroot / "src/spyv/discovery.py",
                toolroot / "src/spyv/bench/scaffolding.py",
            )
        },
        "manifest_sha256": digest(manifest_bytes),
        "seed": SEED,
        "bootstrap_draws": DRAWS,
        "frame": "tracked nonsymlink Python files at pinned commits, standard skip directories excluded",
        "unit": "candidate construct-field occurrence; definitions separate from use-like shapes",
        "warning": "Descriptive conditional yield; no human validation, coverage or soundness claim.",
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (out / "manifest.yaml").write_bytes(manifest_bytes)
    repos = []
    for index, entry in enumerate(entries, 1):
        t0 = time.monotonic()
        root = cache / entry["name"]
        sha = git(root, "rev-parse", "HEAD").decode().strip()
        if sha != entry["sha"]:
            raise RuntimeError(f"Pin mismatch: {entry['name']}")
        if git(root, "diff", "HEAD", "--name-only", "--", "*.py").strip():
            raise RuntimeError(f"Tracked Python modifications: {entry['name']}")
        tracked = [p.decode() for p in git(root, "ls-files", "-z", "--", "*.py").split(b"\0") if p]
        counts = defaultdict(Counter)
        errors = []
        file_rows = []
        records = []
        for relative in sorted(tracked):
            path = root / relative
            parts = PurePosixPath(relative).parts
            if any(p in _SKIP_DIRS or p.endswith(".egg-info") for p in parts):
                errors.append({"file": relative, "reason": "excluded_directory"})
                continue
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
                errors.append({"file": relative, "reason": "symlink"})
                continue
            try:
                raw = path.read_bytes()
                encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
                source = raw.decode(encoding)
                ast.parse(source)
                scoped = sites_in_source(source, relative)
                literal = sites_in_source(source, relative, literal_only=True)
            except (OSError, UnicodeError, SyntaxError, RecursionError, ValueError) as exc:
                errors.append({"file": relative, "reason": type(exc).__name__})
                continue
            if [identity(s) for s in scoped] != [identity(s) for s in literal]:
                raise AssertionError("Ablation changed inventory")
            file_rows.append({"file": relative, "sha256": digest(raw), "candidates": len(scoped)})
            for s, b in zip(scoped, literal, strict=True):
                unit = "definition" if s.construct.startswith("const.") else "use"
                original = stratum(relative, entry.get("demonstrative", False))
                alternative = stratum(relative, entry.get("demonstrative", False), False)
                record = {
                    "id": digest(json.dumps([sha, *identity(s)]).encode()),
                    "file": relative,
                    "line": s.line,
                    "span": [s.call_line, s.call_col, s.call_end_line, s.call_end_col],
                    "construct": s.construct,
                    "unit": unit,
                    "stratum": original,
                    "without_scripts": alternative,
                    "scoped": s.visibility,
                    "literal": b.visibility,
                    "reason": s.reason,
                    "text_sha256": digest(s.text.encode()) if s.visibility != "opaque" else None,
                }
                records.append(record)
                for method, site in [("scoped", s), ("literal", b)]:
                    for u in ("all", unit):
                        for p in ("all", original, "without_scripts_" + alternative):
                            counts[f"{method}/{u}/{p}"][site.visibility] += 1
        row = {
            "name": entry["name"],
            "sha": sha,
            "cohort": entry.get("cohort", "original"),
            "framework": entry["framework"],
            "tracked_python": len(tracked),
            "parsed_python": len(file_rows),
            "exclusions": errors,
            "counts": dict(counts),
            "seconds": time.monotonic() - t0,
        }
        repos.append(row)
        folder = out / entry["name"]
        folder.mkdir()
        (folder / "files.json").write_text(json.dumps(file_rows, indent=2) + "\n")
        with gzip.open(folder / "candidates.jsonl.gz", "wt", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
        (folder / "summary.json").write_text(json.dumps(row, indent=2) + "\n")
        print(f"{index}/{len(entries)} {entry['name']}: {len(file_rows)} files, {len(records)} candidates", flush=True)
    result = {
        "metadata": metadata,
        "repositories": repos,
        "summary": summarize(repos),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print("COMPLETE " + str(out / "results.json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("corpus_manifest.yaml"))
    args = parser.parse_args()
    run(args.cache, args.out, args.manifest)

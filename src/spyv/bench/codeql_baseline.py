#!/usr/bin/env python3
"""Independent dataflow baseline: what does CodeQL recover that we do not?

Implements PROTOCOL_CODEQL.md. For each sampled repository this builds a CodeQL
database, asks CodeQL's points-to analysis for every expression it resolves to a
string constant, and joins the answer against the candidate sites our own
analyser reported opaque.

The point is to stop arguing about the residue from inside the tool whose
adequacy is in question. A negative result here means *this engine, with these
libraries, did not resolve the value*; it is not evidence that no engine could.

Usage:
    python codeql_baseline.py --corpus ~/.cache/spyv/corpus \\
        --candidates <corrective-run-dir> --work <scratch> --out <results-dir>
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

QUERY = '''/**
 * @name String-valued expressions
 * @kind table
 * @id spyv/string-valued-expressions
 */

import python
import semmle.python.objects.ObjectAPI
import LegacyPointsTo

from ControlFlowNodeWithPointsTo n, StringValue v, Location l
where
  n.pointsTo(v) and
  l = n.getLocation() and
  exists(l.getFile().getRelativePath())
select
  l.getFile().getRelativePath() as path,
  l.getStartLine() as line,
  l.getStartColumn() as col,
  count(v.getText()) as n_texts
'''

QLPACK = """name: spyv/codeql-baseline
version: 0.0.1
dependencies:
  codeql/python-all: "*"
"""


def ensure_pack(work: Path) -> Path:
    """Create and install the query pack once; reused for every repository."""
    pack = work / "qlpack"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "qlpack.yml").write_text(QLPACK)
    (pack / "strings.ql").write_text(QUERY)
    if not (pack / ".codeql").exists():
        subprocess.run(["codeql", "pack", "install"], cwd=pack, check=True,
                       capture_output=True, text=True)
    return pack


def codeql_strings(
    repo: Path, pack: Path, work: Path, name: str
) -> tuple[set[tuple[str, int, int]], str | None]:
    """Locations CodeQL resolves to a string constant. Returns (locations, error)."""
    db = work / "db" / name
    if db.exists():
        shutil.rmtree(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    build = subprocess.run(
        ["codeql", "database", "create", str(db), "--language=python",
         f"--source-root={repo}", "--overwrite"],
        capture_output=True, text=True,
    )
    if build.returncode != 0:
        return set(), f"database create failed: {build.stderr.strip()[-300:]}"

    csv_out = work / f"{name}.csv"
    run = subprocess.run(
        ["codeql", "query", "run", str(pack / "strings.ql"), f"--database={db}",
         "--output", str(work / f"{name}.bqrs")],
        capture_output=True, text=True,
    )
    if run.returncode != 0:
        return set(), f"query failed: {run.stderr.strip()[-300:]}"
    decode = subprocess.run(
        ["codeql", "bqrs", "decode", "--format=csv", "--output", str(csv_out),
         str(work / f"{name}.bqrs")],
        capture_output=True, text=True,
    )
    if decode.returncode != 0:
        return set(), f"decode failed: {decode.stderr.strip()[-300:]}"

    locs: set[tuple[str, int, int]] = set()
    with csv_out.open() as fh:
        for row in csv.DictReader(fh):
            try:
                # CodeQL columns are 1-based; our spans are 0-based.
                locs.add((row["path"], int(row["line"]), int(row["col"]) - 1))
            except (KeyError, ValueError):
                continue
    shutil.rmtree(db, ignore_errors=True)
    return locs, None


def opaque_candidates(candidates_dir: Path, name: str) -> list[dict[str, Any]]:
    f = candidates_dir / name / "candidates.jsonl.gz"
    if not f.exists():
        return []
    out = []
    with gzip.open(f, "rt") as fh:
        for line in fh:
            c = json.loads(line)
            if c.get("scoped") == "opaque":
                out.append(c)
    return out


def value_positions(repo: Path, cands: list[dict[str, Any]]) -> dict[str, tuple[int, int] | None]:
    """Locate the expression whose text we failed to recover, per candidate.

    The candidate's span covers the *site* -- for a message dict that is the
    ``{`` of the dict, not the value inside it. CodeQL reports positions of the
    expressions it resolves, which are the individual sub-expressions. Joining
    site spans against those compares two different nodes and answers a question
    nobody asked: it would count a resolved dictionary key as evidence that the
    prompt value was recovered.

    The question this experiment exists to answer is narrower. For the specific
    expression our analyser could not read, does CodeQL read it?
    """
    import ast as _ast

    try:  # importable both as a module and as a standalone script
        from .headroom import _locate_expressions
    except ImportError:
        from spyv.bench.headroom import _locate_expressions

    by_file: dict[str, list[dict[str, Any]]] = {}
    for c in cands:
        by_file.setdefault(c["file"], []).append(c)

    out: dict[str, tuple[int, int] | None] = {}
    for rel, group in by_file.items():
        try:
            tree = _ast.parse((repo / rel).read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError, ValueError):
            for c in group:
                out[c["id"]] = None
            continue
        wanted = {(c["line"], c["construct"]) for c in group}
        located = _locate_expressions(tree, wanted)
        for c in group:
            expr = located.get((c["line"], c["construct"]))
            out[c["id"]] = (
                (expr.lineno, expr.col_offset)
                if expr is not None and hasattr(expr, "lineno")
                else None
            )
    return out


def compare(
    cands: list[dict[str, Any]], locs: set[tuple[str, int, int]], repo: Path
) -> dict[str, Any]:
    """Join candidates against CodeQL locations, per the protocol's rules."""
    by_line = {(p, ln) for p, ln, _ in locs}
    covered_files = {p for p, _, _ in locs}
    positions = value_positions(repo, cands)

    matched = line_only = unmatched = not_covered = unlocatable = 0
    examples: list[dict[str, Any]] = []
    for c in cands:
        pos = positions.get(c["id"])
        if pos is None:
            unlocatable += 1
            continue
        line, col = pos
        if c["file"] not in covered_files:
            not_covered += 1
            continue
        if (c["file"], line, col) in locs:
            matched += 1
            if len(examples) < 12:
                examples.append({"file": c["file"], "line": line,
                                 "construct": c.get("construct"),
                                 "reason": c.get("reason")})
        elif (c["file"], line) in by_line:
            line_only += 1
        else:
            unmatched += 1

    adjudicable = matched + line_only + unmatched
    return {
        "opaque_candidates": len(cands),
        "not_covered": not_covered,
        "adjudicable": adjudicable,
        "codeql_resolved": matched,
        "line_only": line_only,
        "codeql_did_not_resolve": unmatched,
        "unlocatable": unlocatable,
        "resolved_rate": matched / adjudicable if adjudicable else None,
        "examples": examples,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--repos", nargs="+", required=True)
    args = ap.parse_args()

    args.work.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    pack = ensure_pack(args.work)

    per_repo: dict[str, Any] = {}
    totals: Counter[str] = Counter()
    for name in args.repos:
        repo = args.corpus / name
        if not repo.exists():
            per_repo[name] = {"error": "repository not in corpus cache"}
            print(f"  {name}: MISSING", flush=True)
            continue
        cands = opaque_candidates(args.candidates, name)
        locs, err = codeql_strings(repo, pack, args.work, name)
        if err:
            per_repo[name] = {"error": err, "opaque_candidates": len(cands)}
            print(f"  {name}: FAILED {err[:80]}", flush=True)
            continue
        res = compare(cands, locs, repo)
        res["codeql_string_locations"] = len(locs)
        per_repo[name] = res
        for k in ("opaque_candidates", "not_covered", "adjudicable", "unlocatable",
                  "codeql_resolved", "line_only", "codeql_did_not_resolve"):
            totals[k] += res[k]
        rate = res["resolved_rate"]
        print(f"  {name}: {res['codeql_resolved']}/{res['adjudicable']} resolved"
              f"{f' ({rate * 100:.1f}%)' if rate is not None else ''}", flush=True)

    pooled: dict[str, Any] = dict(totals)
    pooled["resolved_rate"] = (
        totals["codeql_resolved"] / totals["adjudicable"] if totals["adjudicable"] else None
    )
    payload = {"protocol": "PROTOCOL_CODEQL.md", "repos": per_repo, "pooled": pooled}
    (args.out / "codeql_baseline.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {args.out / 'codeql_baseline.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Corrective experiment protocol — 2026-09-10

This is a post-exploration corrective protocol. The old paper, corpus results and semantic counterexamples have already been inspected. It is not an external preregistration or an untouched holdout evaluation. Freeze this file and the analyzer in Git before the run. Retain the legacy results unchanged.

## Questions and units

Measure candidate-conditioned text recovery, not precision, recall, security risk or the theoretical limit of static analysis. A candidate is a supported syntactic construct/field occurrence. Identity includes commit, relative file, construct and enclosing line/column span. Definitions (`const.*`) and use-like call/message shapes are reported separately and jointly; both may refer to the same instruction. No name filters are added to remove inconvenient candidates. API names are not import-resolved and candidate validity is unverified.

## Analyzer and comparison

Compare direct literal/skeleton recovery with bounded lexical one-hop binding recovery over the SAME detector inventory. This is an ablation, not an independent end-to-end baseline. Classify exact literals as static, recoverable skeletons as partial and unsupported values as opaque. The new scope analysis invalidates conflicting/dynamic writes, parameters, imports, global/nonlocal and walrus targets; explicit namespace access or wildcard import disables propagation in the file. Attribute/object analysis and arbitrary interprocedural computation are unsupported. These safeguards are not a proof of soundness for dynamic Python. Legacy ladder/headroom analyses still use the old resolver and are excluded.

## Inputs and exclusions

Use all 50 existing manifest pins; preserve original 20 and expansion 30 cohorts. Do not refetch moving branches or execute subject code. Require pinned HEAD and no tracked Python modifications. Analyze tracked nonsymlink .py files; apply the existing skip-directory list. Decode declared Python encodings. Record file hashes, exclusions and parse failures. Non-Python local changes are outside the frame and remain untouched. This differs from the old recursive file walk (50,001 files), so old and new totals are not a controlled analyzer-only comparison. No notebook/config-language coverage claim is made.

## Summaries

Report class counts, pooled recovered fraction and median per-repository fraction; exclude empty denominators from medians and report their counts. Repeat by unit, cohort and path stratum. Call the path complement "other", not production or deployed code. Keep the historical demonstrative-repository flag. Repeat the path rule with `scripts` removed. Report paired mean repository gains for the ablation. Percentile bootstrap uses 10,000 repository-resampling draws, seed 20260910; intervals are conditional on this selected corpus, not population inference. No significance threshold, equivalence claim or optimized exclusion rule.

## Artifacts and interpretation

Store per-repository summaries, source hashes, candidate metadata without raw prompt content, manifest and code/environment metadata in the private paper repository. Preserve partial outputs if interrupted; only `results.json` marks completion. Regression tests establish tested semantic behavior, not real-world recovery correctness. Human precision/missed-site audits and an independent baseline remain required before a strong coverage/full-paper claim. Prepare review worksheets without inventing human labels.

Run: `PYTHONPATH=src .venv/bin/python -B -m spyv.bench.corrective_study --cache <corpus-cache> --out <new-output-directory>`.

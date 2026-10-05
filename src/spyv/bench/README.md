# spyv bench — the Measurement Release (v0.4.0)

Measures spyv against a labeled dataset and reports **deterministic-checker
accuracy separately from LLM-judge accuracy** — because they are different kinds
of evidence and must not be blended into one headline number
(see `SPYV-VERDICT-AND-PLAN` T5).

## Three tiers

| Tier | What runs | Needs a key? | Reproducible? |
|---|---|---|---|
| `deterministic` (default) | regex checkers on the prompt (embedded secret/PII) | no | **yes, byte-identical** |
| `llm` | `analyze()` → precision / recall / F1, per-OWASP recall, confusion, consistency | yes | no (LLM) |
| `all` | `llm` + `redteam()` detection rate on exploitable cases | yes | no (LLM) |

## Run it

```bash
# Deterministic tier — no key, fully reproducible (the CI-safe floor):
python -m spyv.bench
# or
spyv bench

# LLM-judge tier (needs an API key):
OPENAI_API_KEY=... spyv bench --tier llm --provider openai --model gpt-4o-mini

# Everything, plus live red-team, plus a 3x consistency check:
OPENAI_API_KEY=... spyv bench --tier all --provider openai --model gpt-4o-mini --repeat 3 --out baseline.json
```

## Metrics
- **precision / recall / F1** with **95% Wilson confidence intervals** (honest at small N).
- **per-OWASP recall** — did the judge catch each expected LLM0x category.
- **confusion matrix** (TP/FP/FN/TN).
- **consistency** (`--repeat K`) — verdict-stability rate + mean score std-dev across K runs.
- **red-team detection rate** — of the known-exploitable prompts, how many a live attack actually breached.

Decision rule for the LLM tier: `predicted_vulnerable = overall_verdict != "ship"`
(spyv's own "ship" = good-to-deploy = safe).

## Exit code
`spyv bench` exits **non-zero if a known deterministic-detectable case is missed**
— a regression guard you can gate CI on (runs with no key).

## Two validation frames, and why there have to be two

Every recovery figure this suite produces is **conditional on the candidate
inventory** — the set of locations the detector enumerates. Two different
questions hang off that, and one sampler cannot answer both.

| | `spyv annotate` | `spyv missed-sites` |
|---|---|---|
| Samples | candidates | **files** |
| Answers | are found sites real, and classified right? | **what was never found?** |
| Protocol | `PROTOCOL_CONTENT.md` | `PROTOCOL_MISSED_SITES.md` |

`annotate` draws from the detector's own output, so by construction it can never
contain a site the detector missed — it measures precision, never recall.
`missed-sites` draws files instead, **including files where nothing was
detected**, and asks a reviewer to read them cold.

```bash
spyv missed-sites --draw 60 --out missed-sites.json   # stratified file draw
spyv missed-sites --label missed-sites.json           # read files, record sites
spyv missed-sites --score missed-sites.json           # weighted estimate
```

The draw is stratified by whether the detector fired, because a uniform sample
would spend nearly all of a reviewer's hours on files with no instruction text
at all. That is only legitimate because every file keeps a **known non-zero
inclusion probability** stored on its record, and the estimator divides by it.
Reporting an unweighted count over this sample would describe the sample's arm
mix rather than the corpus. Intervals resample repositories, not files.

Labels are a person's. Nothing in this module generates them, and AI-assisted
labels are recorded in a separate field that makes the estimate carry a warning.

## Honesty (read before quoting any number)
This ships a **self-authored seed set** (`dataset/seed.yaml`). It is a **smoke
test and regression guard, not a publishable accuracy claim.** A real number
requires **external / held-out labels**, a **larger N**, and the reported
**confidence intervals** — and the deterministic tier's ~100% must never be
conflated with the LLM judge's error. Add your own dataset with
`--dataset path/to/labeled.yaml` (same schema as the seed).

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

## Honesty (read before quoting any number)
This ships a **self-authored seed set** (`dataset/seed.yaml`). It is a **smoke
test and regression guard, not a publishable accuracy claim.** A real number
requires **external / held-out labels**, a **larger N**, and the reported
**confidence intervals** — and the deterministic tier's ~100% must never be
conflated with the LLM judge's error. Add your own dataset with
`--dataset path/to/labeled.yaml` (same schema as the seed).

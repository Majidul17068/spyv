# Changelog

All notable changes to Spyv are recorded here. Dates are release dates.

## 0.4.0 — Measurement release

Spyv can now be gated on in CI, and it measures itself honestly.

### Added

- **SARIF 2.1.0 export** — `--sarif <file>` on `spyv test` and `spyv scan`.
  Findings appear inline on pull requests via GitHub or GitLab code scanning.
  The rule catalog is bounded so alert history stays stable across runs, and
  each result carries a stable fingerprint derived from the finding's identity
  rather than its position.
- **Severity gates** — `--fail-on {none,low,medium,high,critical}`. Exit `1`
  means the gate tripped on a real finding; exit `2` still means spyv could not
  run. A pipeline can finally tell a security finding from a broken invocation.
- **GitHub Action** (`action.yml`) — adopt spyv in one step. SARIF is uploaded
  before the gate is enforced, so alerts are visible on the failing pull
  request. The API key is read from the environment, never from an action input.
- **`spyv bench`** — measures spyv against a labeled dataset and reports the
  deterministic tier (regex checkers, no API key, reproducible) separately from
  the LLM-judge tier (advisory) and the red-team tier. Proportions carry 95%
  Wilson intervals. Exits non-zero when a deterministic-detectable case is
  missed, so the tier that must not regress can gate CI.
- **`spyv corpus`** — measures discovery and the checkers against real
  repositories: yield by construct, agreement with a naive grep baseline, and
  credentials or personal data in already-committed prompts. Evidence is
  redacted by default; `--reveal` refuses to write to stdout.
- **CrewAI `Task` discovery** — `Task(description=…, expected_output=…)` is
  prompt surface and was previously invisible. Found by the corpus benchmark,
  not by intuition: a naive grep baseline surfaced 16 prompt-bearing files
  discovery had missed, and inspecting them revealed 60 `Task(` constructs in
  one repository. On a four-repo corpus this took discovery from 128 to 137
  prompts across 108 to 113 files.

### Changed

- `SourceKind` gains `crewai_task`. Additive — every consumer treats the field
  as an opaque string.
- The deterministic benchmark tier now runs on every push and pull request
  (`.github/workflows/bench.yml`). It needs no secrets.

### Notes on what these numbers mean

The seed dataset is self-authored and small, so `spyv bench` is a regression
guard rather than a published accuracy claim; a real claim needs external,
held-out labels and a larger N. The corpus grep comparison is an agreement
analysis, not a recall estimate — grep is not ground truth and over-triggers on
prose. Its value is the reverse direction: grep-only files are candidate
discovery misses.

## 0.3.0

### Added

- Hybrid judge: deterministic checkers override a lenient LLM verdict, and
  disagreements are flagged rather than hidden.
- Deterministic checker tier for secrets, PII, prompt leakage, and injection
  markers, with custom patterns and an allowlist.
- Judge hardening against manipulation, with self red-team tests proving a
  crafted response cannot flip a verdict.
- `@guard` runtime decorator: deterministic checks on real agent output.
- f-string and concatenated prompt discovery.
- Concurrent project scanning.

## 0.2.0

### Added

- Active red-teaming: `spyv redteam` fires an OWASP LLM Top 10 attack corpus and
  reports which attacks actually breached, rather than predicting that they might.
- `--attack` flag on `spyv test` for a single-turn pass.

## 0.1.0

First non-alpha release: five-pillar static audit (`spyv test`), project-wide
discovery and audit (`spyv scan`), query-conditioned analysis (`spyv probe`),
runtime call tracking, multi-provider support, and CI across Python 3.10–3.13.

# Changelog

All notable changes to Spyv are recorded here. Dates are release dates.

## 0.5.0 — Validation release

0.4.0 could measure how much prompt surface a static reader recovers. It could
not tell you whether that measurement was *right*. This release answers that
question by capturing prompts as they actually materialise at run time, and it
reports several findings that make spyv's own numbers look worse.

### Added — runtime validation

- **`spyv.bench.runtime`** — capture every instruction string an agent
  constructs, by running a repository's own test suite under injected
  constructor hooks. No API key is needed: capture happens at construction,
  before dispatch, so a provider call that fails for lack of a key still reveals
  what the agent was about to send. Hooks cover CrewAI, LangChain, pydantic-ai,
  OpenAI and Anthropic.
- **`compare()`** — diff captured prompts against the static inventory, giving
  site-enumeration recall and recovery correctness. Attribution walks the whole
  first-party stack rather than the innermost frame, because a framework that
  re-materialises a caller's object otherwise looks like a site the static pass
  missed. Matching uses the enclosing expression's line span, since a runtime
  frame reports the line of the call while a site points at the argument inside
  it.
- **`spyv.bench.consequence`** — measure how much interpolation, the
  precondition for prompt injection, a static check actually detects against
  runtime ground truth.

### Added — measurement

- **`spyv.bench.scaffolding`** — split prompt sites into production and
  scaffolding. Test and example code writes prompts as literals for
  pedagogical reasons, so pooling the two inflates any coverage figure. On the
  reference corpus 61.5% of sites are scaffolding, and the per-repository median
  falls from 43.4% to 28.3% once they are separated.
- **`spyv.bench.ladder`** — five analysers of increasing strength (`L0`–`L4`),
  so headroom is reported as a frontier rather than asserted from one
  implementation. `--ladder` and `--stratified` on `spyv.bench.study`.
- **`spyv.bench.annotate`** — draw a stratified sample of prompt sites for hand
  labelling, and score agreement. Refuses to compute recall, and refuses to
  report a kappa for a single annotator.
- Reference corpus expanded from 20 to 50 repositories, 30 of them selected by
  a mechanical procedure fixed before any search was run. Selection queries,
  screening logs and both versions of the screening rule ship with the package.

### Fixed — cases where spyv was wrong in its own favour

- **`textwrap.dedent` over a string literal was classified opaque.** It is the
  ordinary way to write a multi-line prompt in Python, and instances carrying
  hundreds of characters of literal prompt text were being reported as
  unreadable. `dedent`, `cleandoc` and the whitespace-stripping methods now
  resolve at `L4`; `L0` still treats them as calls, correctly. The corpus holds
  540 such sites and fixing them nearly doubled the final rung of the ladder.
- **`callee_outside_repository` conflated three situations.** It fired whenever
  the import graph failed to resolve a name, and was then read as evidence the
  defining source is absent. Split into `callee_in_stdlib`,
  `callee_in_repository_unresolved` and `callee_third_party`: a third of that
  bucket points at source that is plainly present.
- **Residue tallies were truncated** to each repository's top twelve causes and
  the study's top twenty-five, discarding roughly a twelfth of the counts before
  reporting them as shares.
- The capture hook loaded by path rather than importing the `spyv` package, so
  it no longer fails in a subject repository's virtualenv that lacks spyv's
  dependencies, and it records `install_failed` so a run that captured nothing
  is distinguishable from one whose hooks never ran.

## 0.4.0 — Measurement release

Spyv can now be gated on in CI, enforces policy on what an agent actually did,
and measures itself against real code.

### Added — CI

- **SARIF 2.1.0 export** — `--sarif <file>` on `spyv test` and `spyv scan`.
  Findings land inline on pull requests via GitHub or GitLab code scanning. The
  rule catalog is bounded so alert history stays stable across runs, and each
  result carries a fingerprint derived from the finding's identity rather than
  its position.
- **Severity gates** — `--fail-on {none,low,medium,high,critical}`. Exit `1`
  means a real finding; exit `2` still means spyv could not run. A pipeline can
  finally tell a security finding from a broken invocation.
- **GitHub Action** (`action.yml`) — adopt spyv in one step. SARIF uploads
  *before* the gate is enforced, so alerts are visible on the pull request that
  is about to fail. The API key is read from the environment, never from an
  action input, because inputs are echoed in workflow logs.

### Added — runtime enforcement

- **`spyv.policy`** — deterministic tool-call policy with six rule kinds, loaded
  from YAML: `deny`, `arg_limit`, `require_confirmation` (threshold-aware),
  `require_auth`, `require_precedes`, and `no_secret_in_arguments`. No model is
  consulted, so a violation is a fact rather than a judgement.
- **`@guard` enforces it.** The decorator already checked returned text; it now
  also observes the tool calls a run produced and checks them against a policy.
  This reaches what static analysis cannot: a prompt assembled at run time is
  invisible to source reading, but the call it produced is not. Tool-call
  extraction handles OpenAI, Anthropic and plain dict payloads, and degrades to
  "nothing observed" rather than raising inside a decorator wrapping production
  code.
- `no_secret_in_arguments` closes a real blind spot: a credential travelling
  *into* a tool call is a leak even when the model's prose output is clean.

### Added — discovery

- **CrewAI `Task` prompts** — `Task(description=…, expected_output=…)` is prompt
  surface and was previously invisible. Found by measurement, not intuition.
- **Prompts passed by variable** — a prompt assembled into a local and passed by
  name is now resolved through one binding hop. A name bound to two different
  strings is dropped rather than guessed at.

### Added — measurement

- **`spyv bench`** — labelled-dataset benchmark reporting the deterministic tier
  (no API key, reproducible) separately from the advisory LLM-judge and red-team
  tiers, with 95% Wilson intervals.
- **`spyv corpus`** — discovery and the checkers measured against real
  repositories. Evidence redacted by default; `--reveal` refuses to write to
  stdout.
- **A prompt-surface study** — `spyv.bench.visibility`, `headroom`, `project`,
  `content`, and a `study` driver that regenerates every figure of the
  accompanying measurement paper from a 20-repository corpus pinned by commit.
  Interval estimates respect the clustering the protocol declared: repository
  statistics carry cluster bootstraps, and the pooled rate carries a
  design-effect adjustment.
- Two protocols (`bench/METRICS.md`, `bench/PROTOCOL_CONTENT.md`) committed
  before the measurements they govern, each with a kill criterion fixed in
  advance. One of them fired, and the negative result is reported.

### Changed

- `SourceKind` gains `crewai_task`. Additive; every consumer treats the field as
  an opaque string.
- A guard breach is emitted to stderr exactly once. It was previously both
  printed and logged, so logging's last-resort handler wrote the same JSON a
  second time whenever the application had not configured logging — every breach
  was recorded twice.
- The deterministic benchmark tier runs on every push and pull request. It needs
  no secrets.

### What these numbers do and do not mean

The seed dataset is self-authored and small, so `spyv bench` is a regression
guard, not a published accuracy claim. The corpus grep comparison is an
agreement analysis, not a recall estimate. And the study's own headroom
analysis is reported as inconclusive rather than dressed as a bound: most of the
sites its classifier assigned to "runtime-bound" rest on a heuristic rather than
on evidence, which the released result file records alongside the number.

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

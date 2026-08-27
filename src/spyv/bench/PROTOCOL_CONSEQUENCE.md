# Protocol: does prompt opacity have a security consequence?

Pre-registered. Committed before the measurement was implemented or run.

## Why this experiment exists

Everything measured so far is descriptive. The study establishes that a static
reader recovers a median 28.0% of production prompt sites, and a reader is
entitled to ask what follows from that. A measurement without a consequence is a
statistic, not a finding, and this is the most serious criticism the work faces.

We therefore test one concrete consequence, chosen because it is security-relevant
and because runtime capture can settle it without human labelling.

## The claim

Interpolating a runtime value into instruction text is the precondition for
prompt injection: it is the point at which data crosses into the instruction
channel. Any static check for that precondition must read the prompt to see the
interpolation. Where the prompt is opaque, no such check can fire, however good
its rules are.

**Hypothesis.** A static prompt-injection precondition check has materially less
than perfect recall against runtime ground truth, and the misses are concentrated
in sites the analyser classified opaque rather than in sites it read and judged
wrongly.

The second half matters. If the misses were mostly misjudged readable sites, the
problem would be our classifier and fixable by better rules. If they are opaque
sites, the problem is structural and no ruleset repairs it.

## Ground truth

From runtime capture, not from labels. Observations are grouped by the
**authoring site** — the enumerated site reached by walking the observation's
stack — and never by the innermost frame. A framework that re-materialises many
different callers' agents through one internal line would otherwise appear to be
a single wildly-varying site, which measures the framework rather than the code.
This attribution error was found and corrected before the measurement was run.

For each authoring site, let `D` be the set of distinct strings observed.

- `|D| >= 2` → **interpolating**. The site demonstrably produced different
  instruction text on different executions.
- `|D| == 1` and the site was observed at least twice → **constant** under this
  suite.
- observed exactly once → **undetermined**, and excluded from both numerator and
  denominator. A single observation cannot distinguish a constant from a variable.

Ground truth is a **lower bound** on interpolation. A site that interpolates but
happens to receive the same value throughout a test run is recorded as constant,
and a site the suite never exercises is not recorded at all. The measurement
therefore understates how much interpolation exists, which biases *against* the
hypothesis and is the safe direction.

## The static prediction

Taken from the analyser's existing visibility class, with no new classifier:

- `partial` → predicted interpolating (a literal skeleton with holes)
- `static` → predicted constant
- `opaque` → the check cannot fire at all

## What is reported

1. **Recall**: of ground-truth interpolating sites, the fraction the analyser
   classified `partial`, with a Wilson 95% interval.
2. **Decomposition of the misses** into `opaque` (structurally invisible) and
   `static` (read, but judged constant). This is the part that distinguishes a
   ruleset problem from a structural one.
3. The same figures per repository, never pooled only, since the corpus is
   clustered and two repositories are not a sample.
4. The count of undetermined sites, so the reader can see how much of the surface
   the experiment could not adjudicate.

## Decision rules fixed in advance

- If ground-truth interpolating sites number fewer than 10 in a repository, we
  report the raw counts and **decline to compute a rate**. A recall percentage on
  single-digit denominators is noise presented as a measurement.
- The hypothesis is **not** confirmed by a low recall alone. If the misses are
  predominantly `static` rather than `opaque`, we report that our classifier is
  wrong and the structural claim is unsupported, whichever way it falls.
- No site is excluded after seeing whether it helps or hurts.

## What this cannot establish

That any deployed scanner actually fails on these repositories: we measure the
precondition a scanner would need to see, not a scanner. That an interpolation is
a vulnerability: most are benign, and severity is not assessed. That the rate
generalises: it comes from repositories whose test suites run, and a test suite
exercises test code most of all.

# Protocol: missed-site file audit

Frozen before the sampler was written. This audit estimates what the extractor
never saw, which no measurement conditioned on its own output can do.

## Why this is a separate audit

The candidate audit asks whether recognised occurrences are instruction-bearing
and whether recovered text is correct. Both questions start from the extractor's
own inventory, so neither can detect an instruction the extractor never
enumerated. Every yield figure in this work is conditional on that inventory, and
the inventory's completeness is unmeasured.

This audit samples **files**, not candidates, and the person inspecting a file
looks for instruction text regardless of whether anything was detected in it.

## Frame

The same frame as the corrective measurement: tracked, non-symlink Python files
at the pinned commits, excluding the standard skip directories. Files that fail
to parse are in frame and recorded as such --- a file the extractor could not
parse is a file whose sites were all missed, and excluding it would hide that.

## Sampling

A uniform draw over all files would spend almost all of its effort on files
containing no instruction text at all, which is a poor use of a human hour. The
sample is therefore stratified, and the stratification uses detector output:

- **Stratum A**: files with at least one detected candidate.
- **Stratum B**: files with none.

Using the detector to stratify does not condition the *outcome* on the detector,
provided every unit keeps a known, non-zero inclusion probability and estimates
are weighted by it. Stratum B is the only place a wholly-missed file can appear,
so it must be sampled at a non-trivial rate. Both rates, and the resulting
inclusion probability for every drawn file, are recorded with the sample and
must accompany any estimate derived from it.

Draws are seeded and reproducible. The seed is recorded in the sample file.

## What a reviewer records, per file

For each **instruction-bearing** site found by reading the file:

- its location (line, and the construct or expression that supplies the text);
- whether the extractor enumerated it (`detected` / `missed`);
- if missed, why it was plausibly missed: an unsupported framework or API, an
  alias, a dynamic or configuration-driven construction, a name the hint list
  does not match, or a parse failure;
- confidence, with `uncertain` an explicit and permitted label.

A file containing no instruction text is recorded as such. That is a real
observation, not an absence of data, and it carries weight in the estimate.

## Reported

1. Estimated missed-site rate with its sampling weights and an interval,
   reported separately for each stratum and combined.
2. The count of `uncertain` labels, reported rather than resolved silently.
3. A breakdown of missed sites by plausible cause, which is the actionable part:
   it says which extractor gap costs the most.
4. Files that failed to parse, counted separately from files inspected.

## Committed in advance

- **The estimate is reported whichever way it falls.** If the missed-site rate is
  high, every yield figure in this work is conditional on a materially incomplete
  inventory, and the manuscript will say so in those terms.
- Labels are produced by a person reading source. AI-assisted labels, if used at
  all, are recorded in a separate field and never reported as human ground truth.
- No file is dropped after inspection because its result is inconvenient. A file
  drawn is a file reported.
- Where a second independent reviewer labels a prespecified subset, agreement is
  reported. With a single reviewer, no agreement statistic is computed and the
  single-rater limitation is stated.

## What this cannot establish

A sample of files bounds what the extractor misses **in Python source it can
reach**. Instructions held in configuration, data files, notebooks, other
languages, or assembled only at run time are outside this frame, and their
absence from the estimate is not evidence of their absence from the corpus.

----

# Amendment 1: superseding an earlier file sample

Recorded before any file in either sample was read. No label exists against
either draw, so nothing here selects between results.

## What happened

A file sample for this audit already existed, in the manuscript repository:
`revision/audit/missed-site-files.csv`, drawn under seed 20260912 by
`scripts/prepare_revision.py`, and `AUDIT_GUIDE.md` step 5 pointed reviewers at
it. This protocol and its sampler were written without checking for it, and a
second sample of 120 files was drawn under seed 20260924.

Two drawn samples answering one pre-registered question is a defect regardless
of which is better. If both survive to labelling time, whoever labels can choose
the one whose answer they prefer, and no reader can tell that happened. One must
be retired, and the retirement must be recorded rather than performed silently.

## What is retired, and why

The 20260912 sample is retired. The 20260924 sample is the audit.

Both draws are legitimate probability samples with recorded inclusion
probabilities. The reasons for keeping the second are frame and spread, not a
result, because no result exists for either:

- The earlier draw samples 10 repositories of 50, then 10 files from each, so 40
  repositories contribute nothing and the clustering that dominates variance
  everywhere else in this study is concentrated into ten units. The replacement
  spans 34 repositories.
- The earlier frame is built from each repository's parsed-file record, so the
  ten files that failed to parse cannot be drawn. Those are precisely the files
  whose every site was missed, which this audit exists to count.
- The replacement carries an estimator, so the recorded inclusion probabilities
  are actually divided by rather than left for a later script to honour.

## What is given up

The earlier design is simpler and harder to attack. It does not stratify on
detector output, so it raises no question of whether the stratification biased
anything. The replacement does stratify, and relies on Horvitz-Thompson
weighting to undo it. That reliance is now load-bearing, and a reader who
distrusts the weights should be given the per-arm counts, which the estimator
reports separately for exactly this reason.

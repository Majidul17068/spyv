# Protocol: scaffolding stratification

Pre-registered before implementation or measurement. Committed ahead of
`scaffolding.py` so the classifier cannot be tuned to produce a desired result.

## Why

Site counts pool production code with tests, examples and documentation. These are
not the same population. Example code exists to be read, so its prompts are written
as literals for pedagogical reasons; production code assembles prompts dynamically.
Measuring them together produces a number that describes neither, and it is the
statistic most likely to be attacked, because a reader who cares about deployed
systems is not served by a figure dominated by tutorials.

An adversarial re-analysis of this corpus found 71.1% of all sites sit in
scaffolding paths, with static-prompt visibility of 84.6% inside scaffolding versus
27.3% outside. If that holds under a pre-registered classifier, every headline number
in the study is a statement about example code, and must be relabelled.

## Classifier

A file is **scaffolding** if any of the following holds. Otherwise it is
**production**. Path comparison is case-insensitive on POSIX-normalised
repository-relative paths.

1. Any path *component* (directory name) is exactly one of:
   `test`, `tests`, `testing`, `example`, `examples`, `sample`, `samples`,
   `doc`, `docs`, `cookbook`, `cookbooks`, `notebook`, `notebooks`,
   `benchmark`, `benchmarks`, `demo`, `demos`, `tutorial`, `tutorials`,
   `e2e`, `integration_tests`, `fixtures`, `recipes`, `snippets`, `scripts`.
2. The filename matches `test_*.py`, `*_test.py`, or is `conftest.py`.
3. The file extension is `.ipynb`.

Rule 1 uses exact component equality, not substring matching. Substring matching
would classify `latest/`, `contest/`, or `docstring_utils.py` as scaffolding.

Nested placement does not rescue a file: `examples/myapp/src/agent.py` is
scaffolding, because the whole subtree exists to demonstrate rather than to run.

## Declared edge case

A repository whose *entire* content is demonstrative (an examples collection, e.g.
`crewai-examples`) has no production stratum. Such repositories are excluded from
production-only aggregates rather than contributing a zero or near-zero denominator,
and are listed explicitly wherever an aggregate is reported. Their exclusion is
recorded in the output as `excluded_no_production`.

A repository is treated as having no production stratum when its production site
count is zero. This is a property of the measurement, not a judgement about the
repository, and the threshold is zero rather than a tuned minimum.

## Reporting commitments

Made in advance, so that none of these can be dropped if the result is unflattering:

1. Every headline statistic in the study is reported for **production only**,
   **scaffolding only**, and **all paths**, side by side.
2. Whichever stratum the abstract quotes, it must state which one it is.
3. The recoverability ladder is reported per stratum, under **both** `SPV_static`
   and `SPV_partial`, because an adversarial re-analysis found the two metrics
   disagree about which ladder levels yield anything.
4. The library-versus-application comparison is reported per stratum. If its sign
   differs between strata, that reversal is reported as the finding, not resolved
   by choosing a stratum.
5. Per-repository scaffolding share is reported, so a reader can see that the
   pooled figure is driven by a few very large scaffolding trees.

## What this cannot fix

Stratifying by path is a proxy for intent. A file under `src/` may be dead code, and
a file under `examples/` may be the reference implementation users copy verbatim into
production. Path classification cannot distinguish these, and no claim is made that
it does. The production stratum is "code not marked as demonstrative by its
location", which is weaker than "code that runs in deployment".

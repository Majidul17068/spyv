# Protocol: independent dataflow baseline (CodeQL)

Frozen before the experiment was run. Committed ahead of any measurement so the
sample, the join rule and the reporting commitments cannot be chosen after seeing
which way the result falls.

## Why this experiment exists

Our analyser reports a share of prompt candidates whose text it cannot recover,
and earlier drafts described part of that residue as beyond the reach of static
analysis. Two independent reviewers made the same objection: that conclusion was
drawn from a self-built, admittedly unsound extractor, and it was supported by a
decomposition of the residue into categories which are themselves this
analyser's own give-up messages. That reasoning is circular. It was also wrong
where it was checkable --- a category labelled "not reachable by any static
analysis" turned out to contain `textwrap.dedent` applied to string literals.

The only way to answer the objection is to point a production engine at the same
candidates and report what it recovers.

## Question

Of the candidate sites this analyser classifies **opaque**, what fraction can a
production dataflow engine resolve to a string constant?

## Engine and mechanism

CodeQL CLI 2.27.0 with the standard Python libraries. The mechanism is points-to:
for an expression at a site, whether CodeQL infers a `StrValue`. CodeQL is a
dataflow and taint engine rather than a string-constraint solver, so a negative
result means *this engine, with these libraries, did not resolve the value* --- it
is not a proof of impossibility. We will not report it as one.

## Sample

Ten repositories, chosen as those with the **largest absolute count of opaque
candidates** under the current corrective measurement, ties broken by repository
name ascending. Fixed before any database is built.

This deliberately concentrates on where the residue is largest, because that is
where a stronger engine has the most to find and where the claim under test is
most load-bearing. It over-weights large repositories, and the result is
therefore not a corpus-wide estimate. We report it as a sample and say which
repositories are in it.

## Join rule

CodeQL and this analyser must be compared on the same locations.

- A site is identified by `(relative file path, 1-based line, 0-based column)`.
- CodeQL reports 1-based columns; one is subtracted before comparison.
- A CodeQL string-valued expression matches a candidate when the file and line
  agree and the columns agree exactly.
- Where columns disagree but the file and line agree, the pair is counted
  separately as `line_only` and reported, never silently merged into either the
  matched or the unmatched count.

## Coverage of the comparison

The two tools do not necessarily read the same files. Before any rate is
reported we record, per repository: files this analyser parsed, files CodeQL
extracted, and the intersection. Rates are computed over candidates in files
**both** tools read. Candidates in files CodeQL did not extract are reported as
`not_covered` and excluded from numerator and denominator alike.

## Reported

1. Per repository and pooled: opaque candidates, of those how many CodeQL
   resolves to a string constant, and the `line_only` and `not_covered` counts.
2. A worked example of at least one site CodeQL resolves and this analyser does
   not, quoted from source.
3. The converse where it occurs: sites this analyser recovers and CodeQL does
   not. If the engines disagree in both directions we say so rather than
   reporting only the flattering direction.

## Committed in advance

- **Whichever way it falls.** If CodeQL resolves a substantial share of the
  residue, the claim that the residue reflects the programs rather than the
  analyser is weakened, and the manuscript will say so in those terms.
- No site is excluded after seeing whether it helps. The only exclusions are the
  coverage rule above, fixed here.
- If fewer than 30 opaque candidates in the sample are adjudicable, we report
  counts and decline to compute a rate, consistent with the threshold used
  elsewhere in this work.
- A negative result is reported as "this engine did not resolve it", never as
  "no engine can".

## Known limitations, stated before the result

Database construction can fail or partially extract, especially for
repositories with unusual layouts or missing dependencies; failures are reported
per repository rather than dropped. Points-to in CodeQL is bounded and
configuration-dependent, and a different query or a resolved dependency
environment could recover more. This experiment establishes a lower bound on
what a production engine reaches, not an upper bound.

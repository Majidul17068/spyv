# Protocol: corpus expansion from 20 to 50

Pre-registered. Committed before any search was run, any candidate was listed, or
any repository was cloned. The point of committing first is that repository choice
is the easiest place in this study to manufacture a result, and the git history is
the only evidence that it was not.

## Why expand

Two objections to the current corpus are correct and cannot be answered within it.
Twenty repositories is a small sample for a between-repository estimand, and the
per-stratum intervals show it: the production stratum has 19 repositories and
3,559 sites in total. Separately, the corpus is dominated by framework libraries,
whose median scaffolding share is 70.3% against 17.2% for applications. Since the
study's headline is now the production stratum, a corpus weighted toward libraries
is weighted toward exactly the code that stratum excludes.

## The composition problem, stated before it can be discovered

The existing twenty repositories were selected by convenience, not by a rule. The
thirty added here are selected mechanically. A corpus mixing the two has no single
selection process and therefore no clean sampling interpretation.

We do not resolve this by pretending the original twenty were sampled. Every
headline statistic will be reported three ways: **all 50**, **the original 20**,
and **the mechanically selected 30 alone**. The third is the only group with a
defined selection procedure, and it functions as a check on the first. If the 30
disagree materially with the 20, the convenience sample was biased and we report
that as a finding rather than averaging it away.

## Selection procedure

Executed in this order, with no step conditioned on results.

**1. Queries.** These exact GitHub repository-search queries, and no others:

```
language:python topic:ai-agents stars:>200
language:python topic:llm-agents stars:>200
language:python topic:agentic-ai stars:>200
language:python topic:llm stars:>500
language:python topic:rag stars:>500
language:python "crewai" in:name,description,readme stars:>100
language:python "langgraph" in:name,description,readme stars:>100
language:python "autogen" in:name,description,readme stars:>100
```

**2. Ordering.** Results sorted by stars descending, then by full name
ascending as a tie-break. Deterministic and reproducible.

**3. Mechanical exclusions**, applied in order:
- already present in the corpus
- fork, or archived
- pushed more than 18 months before the fetch date (dormant)
- no permissive or weak-copyleft licence detected by the API

**4. Screening**, applied after cloning, uniformly:
- the repository must import at least one framework or provider the analyser
  models: `crewai`, `langchain`, `langgraph`, `autogen`, `llama_index`,
  `pydantic_ai`, `agno`, `camel`, `smolagents`, `openai`, `anthropic`
- the analyser must enumerate at least one prompt site in it

A repository that fails screening is excluded, and the count and reason for every
exclusion is reported. Screening on "has at least one prompt site" is a criterion
about measurability, not about outcome: it does not look at what fraction of sites
are recoverable, which is the quantity under study.

**5. Take the first 30 that pass**, in the order fixed at step 2.

**6. Freeze.** The SHA at clone time is written to the manifest and never
updated. The manifest is committed with SHA fields empty and frozen at first
fetch, matching the procedure used for the original twenty.

## Committed in advance

1. Every headline statistic reported for all 50, the original 20, and the new 30
   separately, whichever way the comparison falls.
2. The scaffolding stratification of PROTOCOL_SCAFFOLDING.md applies unchanged.
   No new stratum is introduced after seeing the data.
3. If fewer than 30 repositories survive screening, we report the number that did
   and do not relax any criterion to reach 30. Relaxing a threshold after seeing
   which repositories fail is how a sampling rule becomes a selection of results.
4. The library-versus-application split is *not* revived by this expansion. It was
   withdrawn as underpowered and post-hoc, and a larger corpus does not make a
   post-hoc grouping pre-registered.

## What this does not fix

Star thresholds select for popular projects, which are plausibly better
documented and more example-heavy than typical private code. The expansion makes
the corpus larger and its selection reproducible; it does not make it
representative of agent code in general, and no claim of representativeness is
made anywhere in this study.

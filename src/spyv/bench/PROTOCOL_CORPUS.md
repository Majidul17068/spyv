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

---

# Amendment 1: screening on declared dependency

Recorded before any recoverability figure was computed for any new repository.
The only measurements taken under the original rule were a site *count*, which is
part of screening, and no `SPV` value was computed for any candidate.

## What the original rule produced

Step 4 as originally written required the repository to *import* a modelled
framework or provider anywhere in its sources. Executed in the fixed order, it
accepted 19 of the first 21 candidates screened, a rejection rate of under 10%.
The accepted set included `huggingface/transformers`, `vllm-project/vllm`,
`PaddlePaddle/PaddleOCR`, `unslothai/unsloth`, `hiyouga/LlamaFactory` and
`Shubhamsaboo/awesome-llm-apps`: a model library, an inference server, an OCR
toolkit, two fine-tuning tools and a curated list of demos.

None of those is an agent codebase. A single `import openai` in one file of a
five-thousand-file OCR project satisfied the rule, and `vllm` alone would have
contributed 1,760 prompt sites, more than every repository in the original corpus
except `crewai`. The rule did not select the population this study claims to
describe, and pooled statistics would have been dominated by code that does not
build agents.

The full candidate list and the original rule's screening log are committed under
`results/corpus_selection/` so this can be checked rather than taken on trust.

## The amended rule

Step 4's first condition is replaced. A repository is screened in when:

**S1.** It declares a *runtime* dependency on a modelled framework or provider,
parsed from `[project.dependencies]` or `[tool.poetry.dependencies]` in
`pyproject.toml`, from a root `requirements.txt`, or from `install_requires` in
`setup.py`. Optional extras, dev groups and test groups do not count: depending on
`openai` to run a test does not make a project an agent system.

**S2.** The analyser enumerates at least one prompt site in it. Unchanged.

A dependency declaration is the project's own statement about what it is built on,
which is what distinguishes a system that uses a framework from one that merely
mentions or tests against it.

## A criterion considered and rejected

We also evaluated requiring at least one prompt site in a *production* path. It
was dropped because it fires for every candidate tested and therefore excludes
nothing. Keeping a criterion that cannot reject is decoration, and it would have
implied a selectivity the procedure does not have.

## Known misclassifications, not tuned away

The amended rule is mechanical and imperfect in both directions, and we state the
errors we already know about rather than adjusting the rule until they disappear.

- `ai-engineering-from-scratch`, a tutorial repository, is *included*: it declares
  `openai` and `anthropic` as runtime dependencies.
- `deer-flow` and `headroom` are *excluded* despite being LLM-centric. Neither
  declares dependencies in a location the parser reads.

We deliberately stopped adjusting the rule at this point. An earlier iteration was
scored against hand-written labels of which repositories "are really agents", and
two of the four apparent failures turned out to be errors in the labels rather
than in the rule. Fitting a selection criterion to a researcher's own intuitions
about the sample is a way of choosing the sample by hand while appearing not to.
The rule is justified by what a dependency declaration means, not by how well it
reproduces our expectations.

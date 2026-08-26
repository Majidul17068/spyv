# Static Prompt Visibility — metric definition

> Written **before** the measurement was run, and committed unchanged, so the
> definition cannot be tuned to flatter the result. The kill criterion below is
> pre-registered for the same reason.

## The question

It is widely asserted that prompts assembled at runtime are invisible to static
analysis — "not visible to static analysis by definition" is the usual phrasing,
and it is the stated reason runtime interception tools exist. The assertion is
repeated everywhere and, as far as we can find, measured nowhere.

So:

> In real agent codebases, what fraction of prompt surface can a static analyzer
> actually recover?

## Definitions

### Prompt site

A **prompt site** is a source location where a string is supplied to a model or
agent framework in a position that framework treats as an instruction. A site is
identified by the *construct*, not by the string, which is what makes the
denominator enumerable without hand-labelling:

| Construct | Fields treated as prompt surface |
|---|---|
| CrewAI `Agent(...)` | `role`, `goal`, `backstory` |
| CrewAI `Task(...)`, `ConditionalTask(...)` | `description`, `expected_output` |
| OpenAI chat messages | `content` where `role == "system"` |
| LangChain | `SystemMessage`, `SystemMessagePromptTemplate`, `("system", …)` tuples |
| Prompt-named binding | a module or class constant whose name matches a prompt hint |
| Prompt file | `.prompt`/`.txt`/`.md` under a prompt directory; YAML/JSON prompt keys |

A site exists **whether or not** its argument is recoverable. `Task(description=self._build())`
is a prompt site with an unrecoverable argument. This is the crux: the site is
static, the content is not.

### Visibility classes

Each site's argument is classified into exactly one of three:

- **`static`** — the full text is recoverable from source without executing the
  program: a string literal, an implicit or explicit concatenation of literals,
  or a name bound exactly once to such a value.
- **`partial`** — an f-string or concatenation with a recoverable literal
  skeleton and one or more interpolated holes. The instruction's shape is
  analyzable; its runtime content is not. Reported separately because a partial
  prompt is genuinely partly analyzable, and folding it into either extreme
  would overstate the case in one direction or the other.
- **`opaque`** — nothing is recoverable without execution: a function or method
  call, a subscript of a runtime value, a name bound to a non-literal, a
  comprehension, or a read from a file, database, or environment.

### The metric

```
SPV_full    = static                     / sites
SPV_partial = (static + partial)         / sites
opaque_rate = opaque                     / sites
```

`SPV_partial` is the generous reading — everything with any recoverable
skeleton counts as visible. It is the number the claim should be judged against,
because using `SPV_full` would flatter the hypothesis.

Reported per repository, per framework, and per construct, with 95% Wilson
intervals, and aggregated with the repository as the clustering unit — repos
differ in size by orders of magnitude, so a raw pooled rate would be dominated by
the largest one.

## Pre-registered kill criterion

> **If `SPV_partial` ≥ 0.85 across the corpus, the hypothesis is not supported
> and the result is reported as a negative finding.**

The claim under test is that static analysis misses a substantial share of prompt
surface. If it does not, that is the answer, and it is worth writing down once
rather than re-framing until something looks positive.

## What this does and does not establish

**Does:** quantifies, for the frameworks modelled, what share of prompt surface a
static analyzer can recover from source.

**Does not:**

- **Generalize beyond the modelled frameworks.** A site in a framework we do not
  model is not counted at all. This makes the denominator a lower bound and is
  the metric's main threat to validity. Mitigation: a naive grep baseline runs
  alongside as a completeness check, and files where grep finds prompt markers
  but no site is enumerated are reported as `unmodelled_candidates` rather than
  quietly dropped.
- **Measure detection accuracy.** Whether spyv's checkers correctly flag a
  recovered prompt is a different question, measured separately by the labelled
  benchmark. This metric is about *reach*, not judgement.
- **Imply anything about severity.** An opaque prompt is not necessarily a risky
  one. The claim is about analyzability alone.
- **Support a recall estimate from the grep comparison.** Grep is not ground
  truth; it over-triggers on prose and under-triggers on unusual constructs. It
  is an agreement analysis and is reported as one.

## Corpus construction

Repositories are pinned by commit SHA in `corpus_manifest.yaml` so the number is
reproducible by anyone. Selection criteria and exclusions are recorded there, in
advance, so the corpus cannot be curated toward a result after the fact.

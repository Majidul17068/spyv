# Runtime validation protocol

## The criticism this addresses

> "The authors have not established that their syntactic prompt-site inventory is a
> valid denominator, nor that their recovered strings are correct."

Both halves are empirical claims, and neither can be settled by more static analysis.
Hand-labelling cannot settle them either: a human reading source code is guessing at
the same thing the tool is guessing at. The only ground truth for "what prompt actually
reached the model" is observing the prompt as it materialises at runtime.

## Method

Capture, not simulation. The subject repository's own test suite runs under injected
`sitecustomize.py`, which monkeypatches the framework's prompt-carrying constructors
and records every instruction string that materialises, together with the Python stack
at the moment of construction.

- No API keys are provided; API-dependent tests fail, and their prompts are still
  captured, because capture happens at construction, before dispatch.
- `-n 0` is mandatory: `pytest-xdist` workers would interleave writes to the shared
  capture file.
- Capture must never break the suite it observes; every hook is wrapped, and failures
  are counted in `hook_errors` rather than raised.

Two quantities are then measured against the static inventory.

**Site-enumeration recall** — of the prompts that actually reached the model, what
fraction trace back to a site the static pass enumerated? This tests the denominator.
An observation counts as traced if *any* first-party frame in its stack matches an
enumerated `(file, construct)`. Innermost-frame attribution is wrong here: a framework
that re-materialises a user's object (copying `role`/`goal` into a fresh `Agent`
internally) yields a second observation whose innermost frame is library code. That is
one authored prompt seen twice, not a site the static pass missed. The two cases are
reported separately as `matched_at_authoring_frame` and `matched_via_framework_reuse`.

**Recovery correctness** — where the static pass claimed to know the text, was it
right? Scored only where an enumerated expression's line span contains the executing
line. Matching on nearest-line-in-file is not sound: a test file with fifty
`Agent(role=...)` constructions will happily pair the wrong two. Runtime frames report
the line of the *call*, while sites point at the *argument* inside it, so sites carry
`call_line`/`call_end_line` and matching uses the span. Observations that resolve only
to a file and construct are reported as `not_line_resolvable` and excluded from
scoring, because text equality there is not attributable to a specific expression.
Opaque sites are excluded from the denominator of correctness: they make no claim to
be wrong about.

## Negative control

A comparison that filters observations by line span could in principle only ever score
self-consistent pairs, reporting 100% regardless of input. To rule this out, static
site texts are corrupted at known rates and the measurement re-run. Correctness must
degrade in proportion. On crewai:

| corrupted | correctness | wrong |
|-----------|-------------|-------|
| 10%       | 89.95%      | 223   |
| 50%       | 48.74%      | 1,138 |
| 100%      | 0.00%       | 2,220 |

`tests/test_runtime.py::test_corrupting_static_text_degrades_correctness_monotonically`
protects this property.

## Threat to validity of this protocol itself

The harness was first validated on synthetic code with known ground truth. It was then
run on crewai, and **two defects were found and fixed after inspecting crewai's
output**: innermost-frame attribution, and nearest-line matching. Fixing a measurement
instrument using the data it is measuring is tuning on test data, and the crewai
numbers below are therefore optimistically biased to an unknown degree.

Two mitigations, neither complete:

1. The negative control above shows the harness discriminates, which the pre-fix
   version also would have.
2. The harness is now frozen. Subsequent repositories are held-out validation, and
   their numbers are reported separately from crewai's.

The honest statement is that crewai is a development set, not a test set.

## What is out of scope

Recall is measured over prompts that the test suite *exercises*. A prompt site never
reached by any test contributes to neither numerator nor denominator. This protocol
therefore validates the inventory's accuracy on exercised code, not its coverage of
the whole repository.

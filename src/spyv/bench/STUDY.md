# Reproducing the measurement study

Every number in the paper comes from this directory. All of it runs without an API
key, and the static measurements are byte-identical across runs.

## Order matters

Protocols were committed before the code that implements them, so the git history
is the pre-registration record. Verify it rather than trusting this file:

```bash
git log --diff-filter=A --format='%h %ad %s' --date=format:'%H:%M:%S' -- \
  src/spyv/bench/METRICS.md src/spyv/bench/visibility.py \
  src/spyv/bench/PROTOCOL_CONTENT.md src/spyv/bench/content.py \
  src/spyv/bench/PROTOCOL_SCAFFOLDING.md src/spyv/bench/scaffolding.py
```

Each protocol must appear before the module it governs. This is weaker than a
third-party registry: a git history can be rewritten, and only the timestamps of
commits that were pushed are witnessed by anyone else.

## 1. Fetch the corpus

```bash
spyv corpus fetch          # clones 20 repositories at pinned SHAs
```

The manifest ships with every SHA populated. It was committed with the SHA fields
empty and frozen at first fetch, so the pins could not be chosen after seeing
results.

## 2. The three research questions

```bash
python -m spyv.bench.study --rq 1     # what can be read
python -m spyv.bench.study --rq 2     # headroom
python -m spyv.bench.study --rq 3     # what the readable prompts contain
```

## 3. The recoverability frontier

```bash
python -m spyv.bench.study --ladder
```

Five analysers of increasing strength over the same corpus. Slow: L3 and above
build a whole-repository import graph per repository.

## 4. Scaffolding stratification

```bash
python -m spyv.bench.study --stratified
```

Emits every headline statistic for production, scaffolding and all paths. The
protocol commits to all three, so a run that reported only one would not be
following it.

Expected, on the pinned corpus:

| stratum | repos | median SPV_partial |
|---|---|---|
| all paths | 20 | 45.8% |
| production | 19 | 28.0% |
| scaffolding | 18 | 55.2% |

Pooled scaffolding share 72.3%. `crewai-examples` is excluded from production
aggregates: it is an examples collection in its entirety, which path
classification cannot detect, so it is declared in the manifest.

## 5. Runtime validation

This one needs a second virtualenv, because the subject repository's own test
suite has to run:

```bash
python3 -m venv /tmp/rt && /tmp/rt/bin/pip install -e ~/.cache/spyv/corpus/crewai/lib/crewai
/tmp/rt/bin/pip install pytest vcrpy pytest-timeout pytest-asyncio pytest-subprocess pytest-recording
```

```python
from spyv.bench.runtime import run_test_suite, load, compare
from spyv.bench.visibility import run_visibility
from pathlib import Path

repo = Path.home() / ".cache/spyv/corpus/crewai"
run_test_suite(repo, "/tmp/obs.json", python="/tmp/rt/bin/python",
               pytest_args=["lib/crewai/tests/", "-q", "-n", "0",
                            "--continue-on-collection-errors"])
obs = load(Path("/tmp/obs.json"))
for o in obs:                                    # runtime paths are absolute
    o.file = str(Path(o.file).resolve().relative_to(repo.resolve()))
    o.stack = [[str(Path(f).resolve().relative_to(repo.resolve())), n]
               for f, n in o.stack]
print(compare(obs, run_visibility(repo, name="crewai").sites))
```

Three things to know before quoting the output.

`-n 0` is required. `pytest-xdist` workers would interleave writes to the shared
capture file.

Install the repository's own source, not the PyPI release of the same name. Static
analysis reads the pinned checkout, so capture must exercise the same code;
`python -c "import crewai; print(crewai.__file__)"` should point inside
`~/.cache/spyv/corpus`.

A run that captures nothing is not the same as a run whose hooks failed. Check
`hook_errors` in the output file: `install_failed` means no measurement happened.
The hooks load by file path and need only the standard library, so they work in a
virtualenv that does not carry spyv's dependencies.

Expected on crewai: 2,801 observations, 96.2% site-enumeration recall, 2,220 of
2,220 checkable recoveries correct.

### The negative control

Correctness of 100% is only meaningful if the procedure can report failure.
Corrupt the site texts and confirm the measurement degrades:

```python
import copy, random
mut, rng = copy.deepcopy(sites), random.Random(17)
for s in mut:
    if s.text and s.visibility != "opaque" and rng.random() < 0.5:
        s.text = "CORRUPTED-" + s.text[::-1]
print(compare(obs, mut)["recovery"]["correctness"])   # ~0.487, not ~1.0
```

`tests/test_runtime.py::test_corrupting_static_text_degrades_correctness_monotonically`
asserts the property.

## What these numbers are not

The runtime figures come from one repository, and it is the one the capture
harness was debugged against, so they are optimistically biased by an unknown
amount. A test suite also exercises mostly test code, which means the correctness
evidence is strongest in the stratum the study shows matters least. Treat them as
a single-subject result.

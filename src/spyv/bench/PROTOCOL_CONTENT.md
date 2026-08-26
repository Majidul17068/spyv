# What is in real prompts — measurement protocol

> Written and committed **before** the measurement was run, so neither the
> definitions nor the kill criterion can be tuned to the result. The visibility
> study used the same discipline and it caught two errors; this repeats it.

## Question

Prompt surface in real agent codebases has been mined for content and evolution,
but not characterised for the security properties practitioners are told to care
about. Using the recoverable prompts from the public corpus:

> What security-relevant content is actually present in the prompts real agent
> codebases ship?

## Denominator

Every prompt site classified `static` or `partial` by the visibility metric — the
text a static tool can actually read. Opaque sites are excluded because their
text does not exist to inspect. Reported as a share of recoverable prompts, never
as a share of all prompt surface, since the latter would silently assume the
unreadable prompts resemble the readable ones.

## Measures

### M1 — Credential exposure
A prompt containing a credential-shaped string, via the existing deterministic
checkers (provider key formats, AWS keys, GitHub tokens, JWTs, private key
headers, bearer tokens).

**The validity threat is placeholders**, and it is the whole ballgame. Public
repositories are full of `sk-YOUR-KEY-HERE` and `AKIAIOSFODNN7EXAMPLE`. A count
that conflates those with live credentials is worthless and would be the kind of
striking-but-false number that gets a paper retracted. Every hit is therefore
classified before it is counted:

- `placeholder` — matches a placeholder vocabulary (`your`, `example`, `xxx`,
  `todo`, `changeme`, `placeholder`, `dummy`, `fake`, `sample`, `test`,
  `<...>`, `{...}`, repeated identical characters), or is the documented AWS
  example key.
- `low_entropy` — Shannon entropy of the secret body below a fixed threshold,
  which real credentials essentially never are.
- `context_excluded` — the file sits under a test, example, docs, fixture or
  benchmark path.
- `plausible` — none of the above.

Only `plausible` is reported as exposure. All four counts are published, so a
reader can recompute under a different rule.

### M2 — Personal data
Prompts containing email addresses, national-identifier patterns, phone numbers,
or Luhn-valid card numbers. Same placeholder and context classification applies;
`example.com` and `555-` numbers are placeholders by construction.

### M3 — Injection surface
A recoverable prompt that interpolates a value into its instruction text — the
`partial` class, plus `.format()` and `%`-style templating in a `static` prompt.
Reported as prevalence only. **No claim is made that an interpolation is a
vulnerability**; establishing that needs a taint path from untrusted input, which
this study does not attempt. It is a count of where untrusted text could land.

### M4 — Declared guardrails
Prompts containing a refusal instruction, a scope limit, or a
do-not-disclose clause, by keyword families fixed in advance. Descriptive: it
measures what developers write, not whether it works. Prompt-level instructions
are known to be bypassable, and this study does not test them.

## Pre-registered kill criterion

> **If `plausible` credential exposure and personal-data exposure are both below
> 0.5% of recoverable prompts, M1 and M2 are reported as a negative result** —
> "real agent prompts rarely embed credentials" — and the paper's centre moves to
> M3 and M4 rather than being re-framed until something looks alarming.

## Ethics and disclosure, fixed in advance

1. **No secret value is ever published**, in the paper, the repository, a commit
   message, or a released dataset. Counts and categories only.
2. Evidence is redacted by default in every output path, which the corpus tooling
   already enforces.
3. If any `plausible` credential is found, the finding is reported privately to
   the repository owner, and the paper states that disclosure occurred without
   identifying the repository or the credential.
4. The public artifact releases per-repository counts, not per-finding evidence.
5. No attempt is made to validate a credential against a live service. Confirming
   a key works would mean using someone's credential, which is not ours to do,
   and `plausible` is honestly weaker than `confirmed` as a result.

## Stated limitations

- Regex checkers have false positives and false negatives; recall against
  unusual credential formats is unmeasured.
- `plausible` is not `live`. It means "not obviously fake", nothing stronger.
- Prompts unreadable to static analysis are excluded and may differ
  systematically from those included. This is the same selection effect the
  visibility study measured, and it bounds every number here.
- Twenty repositories is a small corpus, and library and application code are
  mixed; per-repository figures are reported alongside any pooled figure.

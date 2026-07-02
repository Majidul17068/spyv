# Spyv Acceptable Use Policy (v1)

This policy is enforced by the framework itself. On first run, `spyv init`
displays this text and records your acceptance (name, timestamp, and version)
in `~/.spyv/accepted-aup-v1`. Every Spyv run row includes this attestation.

---

By using Spyv you attest, on your own responsibility, that:

## 1. Authorization

You will only run Spyv against systems you own or for which you hold
explicit written authorization to conduct adversarial security testing.
Unauthorized testing may constitute a criminal offense under laws
including the US Computer Fraud and Abuse Act, the UK Computer Misuse
Act, the EU NIS2 Directive, and equivalent statutes.

## 2. Provider terms

You will comply with the usage policies and terms of service of every
model provider whose endpoints you test through Spyv. Adversarial or
safety-bypass testing typically requires prior written authorization
from the provider (OpenAI, Anthropic, Google, and others).

## 3. Prohibited content

You will not use Spyv to generate, elicit, or persist:

- chemical, biological, radiological, or nuclear (CBRN) uplift content;
- child sexual abuse material or sexualized-minor content;
- non-consensual intimate imagery;
- targeted harassment of identifiable individuals;
- working malware or cyberweapons intended for unauthorized deployment;
- content that violates applicable law in your jurisdiction.

Spyv ships loader-level refusals for CBRN and CSAM categories; opt-in
research extras require separate written attestation.

## 4. Data protection

Findings may contain personal data or secrets extracted from the systems
you test. You are responsible for compliance with applicable data-
protection law (including GDPR, CCPA, PIPEDA, LGPD, and analogous
regimes), for lawful basis of processing, and for honoring data-subject
rights via:

```bash
spyv forget --subject <hash>
```

Spyv defaults to on-write redaction, encrypted-at-rest storage, and a
30-day TTL on raw evidence. These defaults can be tightened but not
loosened without explicit acknowledgment.

## 5. Disclosure

Findings classified as vulnerability disclosures are subject to a default
90-day coordinated-disclosure embargo. You will follow reasonable
coordinated-disclosure practice ([ISO/IEC 29147](https://www.iso.org/standard/72311.html))
before publishing.

## 6. Export controls

You will not use Spyv in any jurisdiction subject to comprehensive US
or EU sanctions, and you will not export functionality of Spyv in
violation of US EAR intrusion-software controls, Wassenaar cyber-
surveillance items, or equivalent regimes.

## 7. No warranty

Spyv is provided "as is" under the Apache-2.0 license. It is a testing
tool. False positives, false negatives, and non-determinism are inherent
to LLM behaviour. You will not rely on Spyv as the sole security control
for a production system.

---

Acceptance is version-scoped. If this policy changes materially in a
future release, Spyv will re-prompt for acceptance.

# Security Policy

## Reporting a vulnerability in Spyv itself

If you find a security issue in Spyv (not in a target you are scanning
*with* Spyv), please email **security@spyv.dev** with:

- A description of the vulnerability.
- Steps to reproduce.
- Impact assessment (data exposed, code execution, privilege escalation).
- Your preferred disclosure timeline.

We aim to acknowledge reports within 72 hours and to ship a fix or
mitigation within 30 days for critical issues.

## Coordinated disclosure

Spyv's default disclosure window for third-party findings (vulnerabilities
in systems tested *by* Spyv) is **90 days from the run timestamp** or
until the vendor ships a fix, whichever comes first. This follows
[ISO/IEC 29147](https://www.iso.org/standard/72311.html) coordinated
disclosure practice.

To publish a Spyv finding before the embargo lifts, use:

```bash
spyv report --run <id> --publish-early=<justification>
```

The justification is recorded immutably on the run.

## Prohibited use

Spyv is a security-testing tool. Use it only against systems you own or
for which you hold explicit written authorization. See
[`POLICY.md`](./POLICY.md) for the full Acceptable Use Policy.

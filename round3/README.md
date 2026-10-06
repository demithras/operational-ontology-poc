# EOO Round 3 — Paladin Adversarial Hypothesis-Driven Development Pack

**Goal:** test whether the already-demonstrated executable operational machinery becomes justified as a **Paladin-class** system when the primary value claim is security, knowledge sovereignty, authority integrity and operational continuity under adversarial conditions.

This is a **research contract**, not an architecture sales document. It is ready for author review and protocol freeze; it does not claim that any Round 3 hypothesis is already supported.

## Why Round 3 exists

Round 2 established that the executable machinery can work: a bounded kernel, hard Function/Action boundary, generic Engine, Git-canonical executable projection and generated capability-aware Toolchain all survived their tests. But the economic thesis that ontology-specific reuse would repay its tax as semantic variety increased was rejected, including the weaker schema+generator follow-up.

Round 3 therefore changes the value question rather than trying to rescue H22:

> Does a Paladin control plane create a material operational-security advantage under hostile multi-agent and partially compromised operation, compared with an equally competent conventional architecture?

## Paladin invariants

```text
P1 Authority integrity
P2 Effect containment
P3 Knowledge sovereignty
P4 Provenance integrity
P5 External truth
P6 Safe continuity
```

These are defined in `threat_model/security_invariants.json`.

## Hypotheses

| ID | Question |
|---|---|
| H23 | Can a fully compromised agent remain effect-contained? |
| H24 | Do delegation, attenuation, expiry and revocation remain correct under concurrency? |
| H25 | Can constitutional authority topology be executed generically without inventing discretionary judgment? |
| H26 | Does knowledge sovereignty hold across supported observable surfaces? |
| H27 | Is decision provenance tamper-evident across evidence/authority/policy/contract history? |
| H28 | Can Byzantine adapters be prevented from becoming hidden authorities or truth oracles? |
| H29 | Does the system preserve safe continuity and deterministic recovery inside a bounded fault envelope? |
| H30 | Does the total Paladin security premium produce measurable value over a strong conventional baseline? |

## Kill-chain

```text
H23 effect containment
  ├── H24 delegation/revocation ── H25 constitutional authority ── H26 knowledge sovereignty
  └── H27 provenance integrity ─── H28 Byzantine adapter boundary

H24 + H27 + H28 ── H29 safe continuity/recovery

H23-H29 ── H30 comparative Paladin value
```

H30 may not be called SUPPORTED merely because H23-H29 are green. It requires a blind fair A/B security-value experiment.

## Non-goals

- Re-proving Round 2 H15-H21 unless a Round 3 attack falsifies an inherited assumption.
- Reopening H22/H22w's semantic-variety efficiency thesis.
- Claiming hardware/kernel/hypervisor security or global Byzantine survival.
- Treating "fail closed" as resilience if legitimate dependency-independent work stops.
- Treating OpenPona, graph storage or ontology vocabulary as security value by themselves.

## Before execution

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
make check
# review REVIEW_CHECKLIST.md
make freeze
```

`make freeze` hashes hypotheses, thresholds, fairness rules, the threat model and upstream-evidence pin. Any material post-reveal change requires a new experiment version and a new freeze.

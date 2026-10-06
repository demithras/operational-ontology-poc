# Changelog

## 2026-09-29 — Round 2 v2 replacement pack

- superseded the earlier, never-executed Round 2 specifications and reused H15-H22 as the next actual evidence ledger;
- fixed Palantir-class target as Language × Engine × Toolchain over Data × Logic × Action × Security;
- removed RDF from the definition of EOO;
- introduced independent backend-neutral IR;
- made OpenPona a falsifiable language candidate rather than an architectural assumption;
- introduced Manufacturing + Project Ontology as two real domains;
- fixed Git as Project Ontology canonical authority for the first self-hosting experiment;
- encoded H15-H22 as executable hypothesis contracts;
- added personalized adversarial HDD agent contract;
- made Python Hypothesis/state-machine testing primary wherever a computable falsifier exists;
- gated H22 against premature two-domain generalization.

## 2026-10-01 — pre-freeze amendments (before any H15-H22 evidence)

- H15: fixed the sidecar boundary (option 1: record holds atoms only; structure must be in the line) with a computable audit procedure;
- H15: pinned OpenPona at corpus commit 97a9b9e (v0.2.0) with token-inventory and grammar hashes;
- freeze now also hashes `ontology/semantic-equivalence.md` and `ontology/direct_dsl_baseline.md`, which define the H15 oracle and baseline;
- dropped machine-local cache entries from `FILE_INDEX.sha256` and regenerated it.

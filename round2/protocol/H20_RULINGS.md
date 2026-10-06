# H20 — orchestrator rulings before the authoritative run (2026-10-02)

Made after the development run exp-h20-dev and BEFORE the authoritative exp-h20-001. Both readings stay computable
from the evidence (numbers.adapter_strict_count_without_exceptions).

| # | Question | Ruling |
|---|---|---|
| 1 | GitStore._msg writes action/execution/base trailers into the Git commit message. ENGINE_PREREG H20 forbids adapters "provenance writing". The audit exception was declared AFTER the first static run flagged it. | **Not a violation.** docs/05 (every durable Project Action is a Git-visible versioned change) and the H18 brief require the commit to carry the execution id and base; the adapter transcribes data the Engine passes and decides nothing. "Provenance writing" in ENGINE_PREREG means the Engine's authoritative ProvenanceLog/journal; the dynamic taint check shows 0 writes to them from 865 adapter calls. **Strict reading (exception rejected): adapter strict count = 1 -> S3 false -> REJECTED via R1.** |
| 2 | Synthetic definitions: 4,194 unique by full content, 1,571 structurally distinct (ids/numbers normalised). min_runs = 3,000. | Unique = distinct full definition, the same measure H15 used for packages (ids included). Floor met; both numbers reported. |
| 3 | Adapters dedupe repeated calls by execution/effect id (external-system behaviour). | Not an Engine idempotency decision: the probe shows the Engine owns idempotency (same key -> same execution, adapter called once). |
| 4 | Static vocabulary audit is blind to an innocuously named policy check (mutant A1b); only the behavioural ok-mode probe catches it. | Accepted as disclosed blind spot; the mutant is killed by the probe, so the suite as a whole detects it. |

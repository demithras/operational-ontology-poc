# Preregistration and freeze procedure

This pack is a draft for review, not already preregistered. There are two freeze stages because comparative thresholds can only be set after the baseline has been measured.

## Stage A: protocol freeze (before any run)

1. Review every `hypotheses/hNN/contract.json`.
2. Review `model/*.json` (invariants C1-C3 and K1-K5, fault classes F1-F10, gated actions).
3. Review `baselines/FAIRNESS.md`: the conventional arm must have every control that plain GitHub and beads offer.
4. Verify `protocol/UPSTREAM_EVIDENCE.json` still pins the intended upstream state.
5. Answer every item in `protocol/OPEN_QUESTIONS.md` and check it.
6. Run `python scripts/check_pack.py`.
7. Run `python scripts/freeze_protocol.py` and commit the generated `protocol/FREEZE.json` before any implementation or run.

## Stage B: baseline pilot, then comparative thresholds

1. Run the **baseline pilot first** (conventional arm only) and record its numbers.
2. Set every comparative threshold in `protocol/thresholds.json` from those numbers, "just above the measured baseline value", before the treatment run.
3. Run `python scripts/freeze_protocol.py --stage thresholds` (refuses while any comparative threshold is null) and commit `protocol/FREEZE_THRESHOLDS.json`.
4. Only then run the treatment arm.

## Per-hypothesis value of information

Written before the run. If no outcome would change the decision, do not run it.

| Hypothesis | Which outcome changes our decision |
|---|---|
| H31 | Baseline detects every seeded double and stale claim: stop H31, coordination by leases is not needed. A miss by the baseline: leases are worth their cost estimate. |
| H32 | Baseline withholds every blocked item: drop the cross-repo view. A miss: build it before anything else in coordination. |
| H33 | Fully configured baseline creates 0 forbidden effects: record "no advantage measured" (H11 pattern), the gate is not needed for merge. A gap (stale approval, F9, F10): the gate is worth building for exactly that gap. |
| H34 | Baseline closes a false done: observer-confirmed closure is the first thing to build. Baseline closes none: drop H34. |
| H35 | Baseline answers all six links from records the actor cannot rewrite: no provenance store. A gap: provenance is worth building for that gap. |
| H36 | Net advantage inside the frozen cost limits: adopt the pattern. Parity or higher cost: adopt only the single mechanisms that won on their own hypothesis. |

## Manipulation check (treatment was really used)

Before any fan-out, pilot **one item per arm**. The treatment arm must show gate or lease calls per item greater than `thresholds.common.treatment_calls_per_item_must_exceed` (0). Zero calls means the treatment was not used and the hypothesis is INVALID, not refuted. Force use if absent, then re-pilot.

## Control arm reach through the file system

The control arm can read treatment artifacts (gate code, lease store, provenance records, seeded manifests) through the file system. Before the run, check for this (separate working directories, read permissions, no shared mounts). After the run, report in `control-arm-fs-reach-report.json` whether any control run read such a file. If it did, flag those runs and report results with and without them. "The fact came from the treatment" is not value if the control reached it anyway.

## After freeze

Any material change after evidence reveal creates a new experiment version and a new freeze. Never edit thresholds, fault-class membership or the cost model in place after seeing results.

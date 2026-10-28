# Preregistration and freeze procedure

This pack is a draft for review, not already preregistered. There is one freeze. Every threshold, absolute and comparative, is fixed by the author before any run (`protocol/thresholds.json`, `comparative_basis`). The baseline pilot only shows whether there is headroom; it does not set thresholds.

## Protocol freeze (before any run)

1. Review every `hypotheses/hNN/contract.json`.
2. Review `model/*.json` (invariants C1-C3 and K1-K8, fault classes F1-F14, gated actions).
3. Review `baselines/FAIRNESS.md`: the conventional arm must have every control that plain GitHub and beads offer.
4. Verify `protocol/UPSTREAM_EVIDENCE.json` still pins the intended upstream state.
5. Answer every item in `protocol/OPEN_QUESTIONS.md` and check it (done 2026-10-28).
6. Run `python scripts/check_pack.py` (fails if any threshold is null).
7. Run `python scripts/freeze_protocol.py` and commit the generated `protocol/FREEZE.json` before any implementation or run.

## Order after the freeze

1. Run the **baseline pilot** (conventional arm only) as a headroom check. The stop rule in `docs/03_pilot_design.md` is unchanged.
2. Run the manipulation check, one item per arm.
3. Run the treatment arm.
4. Compute verdicts against the frozen thresholds.

## Per-hypothesis value of information

Written before the run. If no outcome would change the decision, do not run it.

| Hypothesis | Which outcome changes our decision |
|---|---|
| H31 | Baseline detects every seeded double and stale claim: stop H31, coordination by leases is not needed. A miss by the baseline: leases are worth their cost estimate. |
| H32 | Baseline withholds every blocked item: drop the cross-repo view. A miss: build it before anything else in coordination. |
| H33 | Fully configured baseline creates 0 forbidden effects: record "no advantage measured" (H11 pattern), the gate is not needed for merge. A gap (stale approval, F9, F10): the gate is worth building for exactly that gap. |
| H34 | Baseline closes a false done: observer-confirmed closure is the first thing to build. Baseline closes none: drop H34. |
| H35 | Baseline answers all six links from records the actor cannot rewrite: no provenance store. A gap: provenance is worth building for that gap. |
| H37 | Baseline (dynamic credentials with TTL, IAM conditions, JIT approver) shows 0 violations: record CEILING, stop H37. A miss (self-approval, standing credential, lagging revoke): the gate is worth building for that gap. Between 0.80 and 0.95 the treatment must close at least half of the misses. |
| H36 | Net advantage inside the frozen cost limits: adopt the pattern. Parity or higher cost: adopt only the single mechanisms that won on their own hypothesis. |

## Headroom rule

Every comparative bar is read through `thresholds.headroom_rule`: the absolute bar applies while the baseline rate is at most 0.80; above it the treatment must close at least 50% of the baseline's misses; at 0.95 or more the class is CEILING, not REJECTED. A fixed +20 bar is unreachable by construction above 0.80.

## Manipulation check (treatment was really used)

Before any fan-out, pilot **one item per arm**. The treatment arm must show gate or lease calls per item greater than `thresholds.common.treatment_calls_per_item_must_exceed` (0). Zero calls means the treatment was not used and the hypothesis is INVALID, not refuted. Force use if absent, then re-pilot.

## Control arm reach through the file system

The control arm can read treatment artifacts (gate code, lease store, provenance records, seeded manifests) through the file system. Before the run, check for this (separate working directories, read permissions, no shared mounts). After the run, report in `control-arm-fs-reach-report.json` whether any control run read such a file. If it did, flag those runs and report results with and without them. "The fact came from the treatment" is not value if the control reached it anyway.

## Fault sampling

The number of seeded faults per class follows `thresholds.fault_sampling`: 20 initially, then pre-registered batches of 20 from the frozen injector, until the baseline arm has missed at least 10 faults of that class, capped at 200. The stopping rule depends only on baseline misses, never on treatment results. All batch seeds are pre-registered before the first run. A class with fewer than 10 baseline misses at the cap is recorded as CEILING (no advantage measured, not REJECTED).

## After freeze

Any material change after evidence reveal creates a new experiment version and a new freeze. Never edit thresholds, fault-class membership or the cost model in place after seeing results.

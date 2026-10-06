# Project Ontology contract v3 (H18w, post-hoc)

`ir.json` (v1) and `ir.v2.json` (v2) stay byte-identical. `ir.v3.json` is the default for new runs
(`domains/_pack.py` `DEFAULT_IR`); v1 and v2 remain selectable (`build_pack(ir_version="v2")`, `run_h18.py --ir-version v2`).
Scope is fixed by `protocol/H18W_PREREG.json` `candidate_change_allowed.scope`: exactly two ordinary declarations,
no Engine, Git-store, oracle or harness-legality change.

## Counterexample classes from exp-h18-001 (Engine v1.1 / contract v2)

| class | exp-h18-001 count | cause in v2 |
|---|---|---|
| `supersede_self` (illegal, accepted) | 7 | policy `conflicting_change_denied_with_conflict` is declared in the IR and bound in logic, but no action references it |
| `new_version_chain` (legal, refused) | 61 | `new_experiment_version` writes the new Experiment unlinked; `target_hypotheses` resolves hypotheses through `TESTED_BY`, so a second `new_experiment_version` on `...@v2` finds no hypothesis and the precondition `phase != DRAFT` fails |

Both are reproduced as tests first: `tests/h18/test_v3_h18.py` (`test_v2_RED_*` assert the divergence on v2,
`test_v3_GREEN_*` assert agreement with the oracle on v3), plus the pins in `tests/h18/test_findings_h18.py` and
`tests/domains/test_project_verdict.py` (both now pinned to v2).

## Change 1: wire the conflict policy

`supersede_hypothesis.policy_refs` gains `policy:conflicting_change_denied_with_conflict`
(expression `docs/05#explicit-conflict`, already bound in `logic/policies.py`: successor == hypothesis, or the successor
already succeeds a different hypothesis). No new logic.

## Change 2: link a new Experiment version to its predecessor

A new link type `NEW_VERSION_OF` (Experiment -> Experiment, new version -> the version it continues; at most one per end)
and a third effect of `new_experiment_version` (`NEW_VERSION_OF`, git_change). Logic: payload binding
`{"$src": new, "$dst": old}` in `logic/payloads.py`; `facts.hypotheses_of_experiment` walks `NEW_VERSION_OF` back to the
first `TESTED_BY` experiment (on a v1/v2 package the link type does not exist and the walk is a no-op);
`projection.py` knows the new link for the in-memory Git fake. The action `version` fields of the two changed actions
and the package `version` become `v3`.

## JSON diff v2 -> v3

```diff
--- domains/project/ir.v2.json	2026-10-02 13:19:18
+++ domains/project/ir.v3.json	2026-10-05 10:29:45
@@ -1,7 +1,7 @@
 {
   "package_id": "project-ontology",
   "domain_id": "operational-ontology-poc",
-  "version": "v2",
+  "version": "v3",
   "imports": [],
   "object_types": [
     {
@@ -631,6 +631,21 @@
       "id": "SUPERSEDED_BY",
       "from": "Hypothesis",
       "to": "Hypothesis",
+      "from_cardinality": {
+        "min": 0,
+        "max": 1
+      },
+      "to_cardinality": {
+        "min": 0,
+        "max": 1
+      },
+      "directed": true,
+      "properties": []
+    },
+    {
+      "id": "NEW_VERSION_OF",
+      "from": "Experiment",
+      "to": "Experiment",
       "from_cardinality": {
         "min": 0,
         "max": 1
@@ -986,12 +1001,16 @@
             "git_commit",
             "frozen_at"
           ]
+        },
+        {
+          "target": "NEW_VERSION_OF",
+          "operation": "git_change"
         }
       ],
       "idempotency": "required",
       "outcome_predicate": "Git contains a new Experiment row with a new version and the matching ContractVersion; the old experiment version is unchanged",
       "compensation_action": null,
-      "version": "v1"
+      "version": "v3"
     },
     {
       "id": "start_run",
@@ -1168,7 +1187,8 @@
       "policy_refs": [
         "policy:legal_lifecycle_transition_allowed",
         "policy:historical_binding_preserved",
-        "policy:stale_write_rejected"
+        "policy:stale_write_rejected",
+        "policy:conflicting_change_denied_with_conflict"
       ],
       "preconditions": [
         "phase == EVALUATED"
@@ -1189,7 +1209,7 @@
       "idempotency": "required",
       "outcome_predicate": "Git contains the hypothesis with phase == SUPERSEDED and a SUPERSEDED_BY link to the successor",
       "compensation_action": null,
-      "version": "v1"
+      "version": "v3"
     },
     {
       "id": "record_decision",
```

# Project Ontology contract v2 (for H16-H22)

`ir.json` (v1) is H15's frozen Gate-0 input and stays byte-identical. `ir.v2.json` is the contract the Engine loads
by default for H16-H22.

## Defect found in v1

`attach_evidence` declares two effects: `Evidence` (create) and `PRODUCES` (Experiment -> Evidence). The function
`evidence_count` (and therefore the precondition of `evaluate_hypothesis`) reads `SUPPORTS_OR_REFUTES`
(Evidence -> Hypothesis). Nothing in the lifecycle ever created that link, so evidence attached through the Engine
could never be counted: a derivable SUPPORTED/REJECTED verdict was always refused (count 0). In v1 the link existed
only because the H15 seed pre-declared it. Pinned by `test_FINDING_attach_evidence_does_not_create_the_link_evidence_count_reads`
(run against the v1 IR).

## Fix

`attach_evidence` gets a third effect `{"target": "SUPPORTS_OR_REFUTES", "operation": "git_change"}`, bound to the
link Evidence -> Hypothesis taken from the action inputs; the package version and the action version become `v2`.
Nothing else changes.

## Status

This is an ordinary domain declaration change (a new IR version through the normal Engine path), made before any
H16-H22 evidence exists. It does not touch the frozen protocol, H15's IR, or the Engine.

## JSON diff v1 -> v2

```diff
--- ir.json (v1)
+++ ir.v2.json (v2)
@@ -2,5 +2,5 @@
   "package_id": "project-ontology",
   "domain_id": "operational-ontology-poc",
-  "version": "v1",
+  "version": "v2",
   "imports": [],
   "object_types": [
@@ -1078,4 +1078,8 @@
           "target": "PRODUCES",
           "operation": "git_change"
+        },
+        {
+          "target": "SUPPORTS_OR_REFUTES",
+          "operation": "git_change"
         }
       ],
@@ -1083,5 +1087,5 @@
       "outcome_predicate": "Git contains the evidence artifact bound to the experiment version, commit and environment",
       "compensation_action": null,
-      "version": "v1"
+      "version": "v2"
     },
     {
```

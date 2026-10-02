# Project Ontology logic bindings: provenance

Every behavioural string of `ir.json` is bound in `domains/project/logic/` (95 required items = 16 `git_change` targets served by the
one `("git_change", "*")` adapter + 79 logic bindings; 0 unbound; `tests/domains/test_binding_coverage.py`).
Logic returns booleans/values only and takes no authority decision: the Engine combines them. Readings marked
*modelled* are not read from a source: the docs state a property, not a predicate.

## Functions (`logic/functions.py`)

| function | binding | source |
|---|---|---|
| `evidence_count` | links `SUPPORTS_OR_REFUTES` into the hypothesis | `HypothesisState.evidence_count`, `src/hdd/project_lifecycle_reference.py` |
| `derive_verdict` | `logic/derive.py`: the registered evaluator of `Experiment.evaluator_ref` returns five booleans; the verdict is ALWAYS `src.hdd.verdict.evaluate_common(CommonEvaluation(...))`, never the evaluator's own string and never user input. No evidence attached to the latest experiment version -> no evaluator is called, `required_evidence_complete=False` (never SUPPORTED) | `src/hdd/verdict.py` |
| `compute_freeze_hash` | `logic/freeze.py`: sha256 over `path NUL bytes NUL` of the files named by the experiment's `evidence_schema_ref` then `evaluator_ref` (committed bytes via `git show HEAD:`), then a pseudo-file `threshold:<id>` per governing threshold | `scripts/freeze_protocol.py` (same byte layout); `test_compute_freeze_hash_reproduces_scripts_freeze_protocol_py` reproduces `protocol_sha256` of FREEZE.json from its 13 files and shows a different file set hashes differently |
| `find_orphan_components` | Components with no `EXISTS_FOR` link to a hypothesis whose phase is not SUPERSEDED | docs/04 |
| `canonical_state_hash` | sha256 of the canonical JSON of all rows of the 15 object types, order independent | docs/05 property 1 (weak: store only, see below) |
| `is_legal_transition` | `logic/lifecycle.py`: the guards of `preregister/start/evaluate/supersede` of the independent reference model | `src/hdd/project_lifecycle_reference.py` |

H15 evaluator (`evaluators.py`): the real `eoo_h15.evaluate.evaluate` over the committed evidence files of exactly the
evidence rows attached to the experiment; a row whose `payload_hash` differs from the committed record makes the protocol
invalid (-> INVALID); a missing file is missing evidence (-> INCONCLUSIVE). H16-H22 have no evaluator yet (no evidence).

## Policies, preconditions, constraints (`policies.py`, `actions.py`, `constraints.py`)

docs/04 hard rules 1-6 follow `src/hdd/project_lifecycle_reference.py` (completeness: claim, >=1 rival, >=1 prediction,
>=1 falsifier, an experiment with evidence schema + evaluator; threshold frozen outside DRAFT; RUNNING needs a freeze
hash; EVALUATED needs evidence or an explicit INCONCLUSIVE/INVALID; verdict derived; evidence pinned to experiment
version, commit, environment, payload hash; orphan flagged not deleted). The four docs/05 policies are *modelled*:
`stale-write` = a newer Git version exists (the hypothesis already has a SUPERSEDED_BY successor); `explicit-conflict` =
a hypothesis superseded by itself or a successor that already replaces another; `ephemeral-state` = no input value
starts with `ephemeral:`; `historical-binding` = evidence/contract/experiment versions already bound are never rebound.
Constraints evaluate the would-be state = store + `ctx.planned` (the Git payloads about to be written). Weak ones, stated:
`rebuild-reproduces-state-hash` (only order independence of the hash: there is no Git rebuild in the store-only Engine),
`conflicts-surface-explicitly` (only conflicts inside one action are visible to one evaluation).

## resource_selector texts outside the Engine grammar (`logic/selectors.py`)

| text | rules | meaning bound |
|---|---|---|
| `ProjectOntology:*` | researcher-edit-threshold, -new-experiment-version, -start-run, -attach-evidence, -record-decision, -flag-orphan-component, no-canonical-write-outside-git | true iff the request touches at least one resource and every resource it touches is an object type or link type of this package (a request reaching outside the package does not match) |
| `Threshold:preregistered` | no-threshold-edit-after-preregistration | true iff some resource is a Threshold governed (Metric <- MEASURES <- Experiment <- TESTED_BY <- Hypothesis) by at least one hypothesis whose phase is not DRAFT |

Both return booleans only. The deny rule `no-threshold-edit-after-preregistration` requests capability `update:Threshold`,
which the pipeline never asks for, so the effective block is the policy `threshold_edit_after_preregistration_denied`
and the precondition `phase == DRAFT` (each shown alone in the tests).

## git_change effects and the projection

`git_change` effects go to the adapter, never to the store (Engine semantics section 6). `adapters/git_fake.py` is an
in-memory commit log (content-addressed: the same effect id + target + row returns the same commit; modes `ok|corrupt|
timeout`, `observe=False` for lag). `projection.py` rebuilds the store from base seed + every Git commit; tests boot a
fresh Engine on it between lifecycle steps (Git canonical, ontology rebuildable). `seed_from_repo.py` builds the seed from
real committed artifacts via `git show HEAD:<path>` (FREEZE.json, thresholds.json, H15-H22 contracts, exp-h15-001/002
evidence records and verdict.json); read-only. *Modelled, not read*: Component list and their `EXISTS_FOR` links,
principals, experiment ids/versions for H16-H22 (`exp-hNN-001`, version 1, evaluator_ref = `hypotheses/hNN/contract.json#evaluator`).

## Findings on the frozen Project IR (reported, not patched)

1. Policy `conflicting_change_denied_with_conflict` is referenced by no action's `policy_refs`, so the Engine never
   evaluates it; superseding a hypothesis by itself is accepted. The binding is correct (denies when referenced:
   `test_FINDING_conflicting_change_policy_is_bound_but_no_action_references_it`).
2. `attach_evidence` creates only `PRODUCES`, while `evidence_count` reads `SUPPORTS_OR_REFUTES`. A SUPPORTED verdict
   needs `evidence_count >= 1`, so unless the link is pre-declared with the evidence the evaluate step is refused
   (`test_FINDING_attach_evidence_does_not_create_the_link_evidence_count_reads`).
3. Authority deny rules `no-direct-verdict-write` / `no-threshold-edit-after-preregistration` /
   `no-canonical-write-outside-git` use capabilities (`write:Verdict.value`, `update:Threshold`, `write:canonical-state`)
   the pipeline never requests, so they never fire; the equivalent protection comes from policies/constraints/inputs.

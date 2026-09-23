# 07 — Versioning, Migration, and Replay

## Core rule

A historical decision is evaluated under the contract that existed when it was made, unless the operator explicitly requests a counterfactual re-evaluation under a newer contract.

Do not rewrite history by silently applying today's policy to yesterday's decision.

## Versioned artifacts

At minimum:

```text
ontology schema
SHACL shapes
action definitions
OPA policy bundle
OpenFGA authorization model
identity mapping rules
projection definitions
decision-service code
reconciliation predicates
```

## Version identifiers

Prefer immutable content hashes plus human-readable versions.

Example:

```yaml
ontology:
  semver: 1.2.0
  sha256: ...

policy_bundle:
  name: supply-v17
  sha256: ...

action:
  name: transfer_inventory
  version: 3
  sha256: ...
```

## Evidence snapshot requirements

A decision's evidence must be reconstructable.

The POC may implement snapshots as:
- immutable RDF named graph; or
- content-addressed manifest + immutable event positions; or
- hybrid.

The experiment must prove reconstruction, not merely claim it.

## Required migration experiment

### V1

```text
fac:Part
fac:availableQuantity
transfer_inventory v1
policy v1
```

Create at least 100 decisions.

### V2 breaking change

Example:
- rename/split `availableQuantity`;
- introduce `onHand` and `reserved`;
- change safety-stock policy;
- add required evidence field;
- update action schema.

Create another 100 decisions.

### V3

Add a second incompatible evolution and migrate current state.

Then run:

```text
replay(all V1 decisions)
replay(all V2 decisions)
```

## Replay output

```yaml
decision_id: D-...
original:
  evidence_hash: ...
  ontology_version: ...
  shape_version: ...
  authz_version: ...
  policy_version: ...
  action_version: ...
  gate_results:
    authorization: allow
    policy: allow
    conformance: pass
  proposed_action: ...
  observed_outcome: ...

replay:
  reconstructed: true
  evidence_hash_match: true
  gate_result_match: true
  action_input_match: true

status: PASS
```

## Counterfactual replay

Separate command:

```text
reevaluate --decision D --under current
```

This answers:

> What would today's rules decide given the historical evidence?

It must never overwrite or be confused with historical replay.

## Compatibility CI

Any contract change runs:

1. syntax validation;
2. SHACL tests;
3. policy tests;
4. OpenFGA model tests;
5. action-schema compatibility checks;
6. migration fixture tests;
7. replay corpus;
8. projection rebuild test.

A breaking change without migration/replay fixture fails CI.

## Projection rebuild

Delete all hot projections and reconstruct them from semantic/source history.

Required:

```text
hash(rebuilt_projection) == hash(expected_projection)
```

for stable deterministic fields, with documented exclusions for timestamps/technical IDs.

## Retention

For the POC, retain the complete experiment history.

Production retention policy is out of scope, but the design must make explicit that deleting evidence or old contract versions can destroy replayability.

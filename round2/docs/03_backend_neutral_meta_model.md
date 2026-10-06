# 03 — Backend-neutral meta-model under test

This file defines the independent semantic target against which candidate languages are judged. It is intentionally **not OpenPona-shaped**.

## Required resource kinds

```text
OntologyPackage
ObjectType
Property
LinkType
Interface
Function
Action
Policy
AuthorityRule
ObservationType
Constraint
ContractVersion
```

Project Ontology adds ordinary domain object types such as Hypothesis, Evidence and Commit; those are **not kernel primitives**.

## Function vs Action

A `Function`:

- accepts typed inputs;
- may read allowed ontology state;
- returns typed output;
- has no externally committed business side effect under the ontology contract.

An `Action`:

- represents an intended governed change;
- has explicit authority/policy/precondition requirements;
- can produce a committed external or canonical-state side effect;
- records execution identity/version/provenance;
- has outcome observation/reconciliation semantics.

A function may help compute an action proposal. It may not smuggle the action's write capability through a supposedly pure API.

## Why the IR is independent

H15 would be circular if OpenPona defined both the candidate language and the oracle. The JSON schema under `ontology/ir.schema.json` is therefore the normative test target for Round 2 v2 language compilation. It may evolve **before protocol freeze**, but once H15 is frozen it is part of the oracle.

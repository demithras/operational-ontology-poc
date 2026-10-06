# 09 — Python `hypothesis` strategy

## Governing rule

**Every research hypothesis should be executable where possible; not every research hypothesis is a Python `@given` test.**

Use `hypothesis` when the target claim has a meaningful generated state/input space and a computable oracle.

## H15 — OpenPona language

Generate valid IR fragments and whole packages:

```text
object types
properties/types/cardinalities
links
interfaces
function signatures
pure function bodies as abstract operations
actions/effects
policy/authority references
versions/constraints
```

Then test:

```text
IR -> OpenPona -> IR'  => semantic_equivalent(IR, IR')
```

Also generate invalid/ambiguous OpenPona to ensure it fails closed rather than inventing types.

## H16 — bounded kernel

Generate compositions from both registered domains and synthetic combinations of their legal resource kinds. Assert that the language/compiler/runtime dispatches by generic kind/capability rather than domain identity.

The final verdict also needs static/diff evidence showing zero new kernel primitives.

## H17 — Function vs Action

Use `RuleBasedStateMachine` to interleave:

```text
read
call function
propose action
deny action
approve action
retry
crash/restart
execute
observe outcome
```

Inject a mutation that gives a Function write capability. The suite must find it.

## H18 — Project Ontology

Generate lifecycle sequences and hostile edits:

```text
create hypothesis
preregister
change threshold after freeze
attach wrong-version evidence
evaluate without evidence
force verdict
supersede
orphan component
```

Compare against a simple independent transition model.

## H19 — Git authority

Generate commit/action interleavings, stale base versions, conflicts, rebuilds and merges. Assert canonical hash convergence or explicit conflict; never silent lost updates.

## H20 — generic Engine

Generate valid operations over both domain schemas and assert identical generic dispatch paths/invariants. Static instrumentation should fail if runtime code branches on domain identity.

## H21 — Toolchain/security

Generate principals, capabilities, object sets and action permissions. Differentially compare generated SDK/tool visibility and runtime authorization against the independent authority oracle.

## H22 — semantic variety break-even

Hypothesis can generate adversarial workload/query/policy shapes, but the final claim is a trend/cost comparison across **real domains**. A property test cannot substitute for that evidence.

## Mandatory mutation proof

Every major property/state-machine suite must include at least one injected bug from the target failure class and demonstrate detection. Prefer shrinkable bugs so the failing sequence becomes diagnostically small.

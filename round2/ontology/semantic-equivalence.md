# Semantic equivalence oracle for H15

H15 needs a syntax-independent definition of when two IR packages mean the same thing.

## Normalize before comparing

A normalizer may:

- sort resource arrays by stable ID;
- sort unordered lists such as authority references where order has no semantics;
- expand defaults explicitly;
- normalize equivalent primitive type spellings;
- canonicalize object keys;
- resolve imports to pinned version identifiers for comparison.

It may **not**:

- infer missing cardinality;
- turn a Function into an Action or vice versa;
- invent authority/policy refs;
- fill a missing version from current state;
- change required/immutable flags;
- erase Action effect/outcome semantics;
- erase Interface capability requirements.

## Equivalence classes

Two normalized packages are semantically equivalent only when all frozen resource kinds preserve:

```text
resource identity
property name/type/required/immutable constraints
link endpoints/cardinality/direction
interface shape/capability requirements
function input/output/purity/read set/implementation identity
Action inputs/governance/effects/idempotency/outcome/version
policy decision/expression/version
authority principal/capability/resource/effect/delegation
observation subject/source/truth status
hard/soft constraints
package/import versions
```

Surface formatting, comments and resource ordering do not matter.

## Independence rule

The equivalence implementation must operate on IR only. It must not parse OpenPona or ask the OpenPona compiler what a missing field "probably meant".

## Sidecar boundary for H15 (fixed before freeze, 2026-10-01)

OpenPona keeps values out of the line and puts them in a record next to it. For H15 the record may hold **atoms only**: identifier spellings, opaque expression/reference strings (`implementation_ref`, `expression_ref`, `outcome_predicate`, preconditions, selectors, capability strings, `source_binding`, descriptions) and literal values (versions, numeric cardinality bounds) filling a slot the line declares.

Everything structural must come from the line: the kind of each resource, every enum and boolean, primitive types and type constructors, the reference graph, which slot each literal fills, and the Function/Action distinction.

The audit is computable: alpha-rename every record atom and require the compiled IR to equal the renamed IR; replace every atom with a placeholder and require the full IR shape to be recovered from the line alone. The authoritative version is `hypotheses/h15/contract.json` → `experiment.sidecar_classification`.

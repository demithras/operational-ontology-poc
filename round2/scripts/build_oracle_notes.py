#!/usr/bin/env python3
"""Write ontology/h15_oracle_notes.md (static decisions + the mutation-class table generated from the registry)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eoo_ir.mutations import REGISTRY  # noqa: E402

HEAD = """# H15 independent IR oracle: decisions and self-test table

Status: written in H15 Phase 1 (Gate 0), before any candidate surface exists. Part of the Gate-0 hash
(`protocol/H15_GATE0.json`). Code: `src/eoo_ir/`. Nothing in that package imports, mentions or depends on the
candidate language (AGENTS.md section 10; enforced by `tests/h15/test_oracle_static.py`).

## 1. What "equivalent" means here

`equivalent(a, b)` is **equality of the fully normalized packages over every field**, including `description`,
`determinism`, `domain_id`, `imports` and `metadata`. `ontology/semantic-equivalence.md` lists what two packages must
preserve "only when" they are equivalent; that list is a necessary condition. This oracle is deliberately **stricter**:
a surface that silently drops a description, a determinism flag, a domain id or a metadata key is reported as losing
information, because the experiment's claim is *lossless* and a field the minimum list forgot is exactly where loss hides.
Equality is decided on canonical JSON text, so `true`, `1` and `1.0` are three different values.

## 2. Normalization (and only this)

| allowed by semantic-equivalence.md | what the code does |
|---|---|
| sort resource arrays by stable id | each of the 9 arrays sorted by `id` (ties broken by canonical JSON) |
| sort unordered lists | sorted, **duplicates kept** (`[a]` and `[a, a]` differ): `implements`, `reads`, `authority_refs`, `policy_refs`, `required_links`, `capabilities`, `imports`, `preconditions`, property `constraints`, effect `fields` |
| (property arrays are name-keyed sets) | `object_types[].properties`, `link_types[].properties`, `interfaces[].required_properties` sorted by `name`; `observation_types[].properties` too (same reason: a name-keyed set; this is a judgement, not a quoted rule) |
| expand defaults explicitly | `immutable=false`, `constraints=[]` (property); `directed=true`, `properties=[]` (link); `required=true` (parameter); `delegation_allowed=false` (authority rule); `imports=[]` (package). Nothing else has a schema default |
| canonicalize keys | object keys sorted at every level (metadata included); metadata arrays keep their order |
| normalize equivalent primitive type spellings | no-op: the schema has exactly one spelling per primitive |
| resolve imports to pinned version identifiers | no-op: `imports` entries are already opaque identifier strings |

**Order-significant (kept as given):** function `inputs`, action `inputs`, action `effects`.

**Never done:** inferring cardinality, kind, authority/policy refs, version or flags; filling a missing optional field
(absent stays absent: no default exists for `compensation_action`, `determinism`, `domain_id`, `description`, `metadata`,
effect `fields`); treating `null` as absent (`compensation_action: null` differs from no `compensation_action`);
merging duplicates; moving a resource between kinds (Function vs Action).

## 3. Validity (what the generators and the real-domain files must satisfy)

`eoo_ir.validate` = the frozen JSON Schema **plus** referential integrity. A reference resolves against the ids of the
kinds its slot allows; zero matches is `unresolved_ref`, more than one distinct match is `ambiguous_ref`.

| slot | resolves to |
|---|---|
| `link_types[].from/to`, every `{"ref": x}` type | object type **or interface** (so a link may end at an interface) |
| `object_types[].implements[]` | interface |
| `object_types[].primary_key` | a property name of that object type (so an object type needs at least one property) |
| `interfaces[].required_links[]` | link type |
| `functions[].reads[]` | object type, link type or observation type id, or `<Type>.<property>` of one of them |
| `actions[].authority_refs[]` | `auth:<authority rule id>` (spelling of the frozen examples) |
| `actions[].policy_refs[]` | `policy:<policy id>` |
| `actions[].effects[].target` | by operation: create/update/delete -> object type; link/unlink -> link type; git_change -> object or link type; **external_call -> opaque system name, not resolved** |
| `actions[].effects[].fields` | property names of the locally resolved target (opaque for external_call and imported targets) |
| `actions[].compensation_action` | action id (self reference allowed), or null/absent |
| `observation_types[].subject_type` | object type |

Also: ids unique per kind; property names unique per owner; parameter names unique per function/action.
A reference that matches nothing locally may be import-qualified, `<import>#<name>` with `<import>` an entry of `imports`;
it is accepted without further checking (this `#` convention is the oracle's own: the schema only says imports are strings).
Opaque atoms (never resolved): `constraint.scope`, authority selectors and capability, `expression_ref`,
`implementation_ref`, `outcome_predicate`, `source_binding`, preconditions, capabilities, descriptions, property constraints.

Interface conformance (implementers really have the required properties/links) is **not** part of validity (the
schema does not ask for it); `eoo_ir.conformance` checks it and the two real-domain files pass it.

Cardinality orientation (not defined by the schema; read off the frozen example `HypothesisHasEvidence` {0,*}/{1,1}):
`from_cardinality` = how many links a FROM instance has, `to_cardinality` = how many links a TO instance has.

## 4. Generators and rewrites

`valid_packages()` (Hypothesis) builds referentially consistent packages: ids first, bodies after; object types and
interfaces draw ids from disjoint pools; link types sometimes reuse an object-type id and actions sometimes reuse a function
id so that ambiguity and Function/Action-with-same-id cases occur; the empty string appears wherever the schema allows it
(no `minLength`); atoms include unicode, spaces, quotes, newlines and keyword-like strings. `rewrite()` /
`allowed_rewrite(pkg)` only reorders (resources, set-valued lists, properties, key order) and expands defaults.

## 5. Self-tests

* every `allowed_rewrite` is equivalent (and still valid); every mutation class below is judged **not** equivalent and
  the diff path names the mutated field (`tests/h15/test_oracle_equivalence.py`);
* hand-written known negatives (cardinality max 1 vs `*`, Function vs Action of the same id, authority allow vs deny,
  dropped package/action/policy version, required true vs false, optional vs non-optional type, absent vs null
  `compensation_action`, `true` vs `1` in metadata, effect order): `tests/h15/test_oracle_known_negatives.py`;
* oracle meta-tests: known defects are injected into the normalizer (sorting effects/inputs, de-duplicating
  preconditions, filling `compensation_action`, dropping metadata/descriptions/versions, equating `*` with a large integer,
  collapsing Function and Action; and the opposite family: no default expansion, no set sorting, no property sorting, identity
  normalizer) and the suite must notice each: `tests/h15/test_oracle_meta.py`. The first run of this meta-test found a real gap
  (no mutation class distinguished `*` from a huge integer); `cardinality_star_vs_large_int` was added;
* coverage: a fixed-seed sample of 2,000 generated packages must reach every item of `eoo_ir.coverage.expected()`
  (`tests/h15/test_oracle_coverage.py`). One item is impossible by construction and excluded: an object type with zero
  properties (its primary key could not resolve).

## 6. Mutation classes (one structural field each)

Generated from `eoo_ir.mutations.REGISTRY`; `field` is the substring that must appear in a diff path.

| class | family | field | what changes |
|---|---|---|---|
"""


def main() -> None:
    rows = "".join(f"| `{c.id}` | {c.family} | `{c.field}` | {c.description} |\n" for c in REGISTRY.values())
    out = ROOT / "ontology" / "h15_oracle_notes.md"
    text = HEAD + rows + f"\n{len(REGISTRY)} classes.\n"
    if "--check" in sys.argv:
        ok = out.exists() and out.read_text() == text
        print("OK notes up to date" if ok else "STALE ontology/h15_oracle_notes.md")
        raise SystemExit(0 if ok else 1)
    out.write_text(text)
    print(f"wrote {out.relative_to(ROOT)} with {len(REGISTRY)} mutation classes")


if __name__ == "__main__":
    main()

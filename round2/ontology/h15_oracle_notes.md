# H15 independent IR oracle: decisions and self-test table

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
| `package_id` | package | `package_id` | package_id changed |
| `package_version` | package | `version` | package version changed |
| `domain_id` | package | `domain_id` | domain_id changed or added |
| `imports` | package | `imports` | import element changed or added |
| `metadata` | package | `metadata` | metadata key added/changed |
| `metadata_bool_vs_int` | package | `metadata` | metadata true<->1 / false<->0 |
| `remove_object_types` | resource | `object_types[` | a object_types resource removed |
| `add_object_types` | resource | `object_types[` | a object_types resource added (copy, new id) |
| `rename_object_types` | resource | `object_types[` | a object_types id renamed (identity change) |
| `remove_link_types` | resource | `link_types[` | a link_types resource removed |
| `add_link_types` | resource | `link_types[` | a link_types resource added (copy, new id) |
| `rename_link_types` | resource | `link_types[` | a link_types id renamed (identity change) |
| `remove_interfaces` | resource | `interfaces[` | a interfaces resource removed |
| `add_interfaces` | resource | `interfaces[` | a interfaces resource added (copy, new id) |
| `rename_interfaces` | resource | `interfaces[` | a interfaces id renamed (identity change) |
| `remove_functions` | resource | `functions[` | a functions resource removed |
| `add_functions` | resource | `functions[` | a functions resource added (copy, new id) |
| `rename_functions` | resource | `functions[` | a functions id renamed (identity change) |
| `remove_actions` | resource | `actions[` | a actions resource removed |
| `add_actions` | resource | `actions[` | a actions resource added (copy, new id) |
| `rename_actions` | resource | `actions[` | a actions id renamed (identity change) |
| `remove_policies` | resource | `policies[` | a policies resource removed |
| `add_policies` | resource | `policies[` | a policies resource added (copy, new id) |
| `rename_policies` | resource | `policies[` | a policies id renamed (identity change) |
| `remove_authority_rules` | resource | `authority_rules[` | a authority_rules resource removed |
| `add_authority_rules` | resource | `authority_rules[` | a authority_rules resource added (copy, new id) |
| `rename_authority_rules` | resource | `authority_rules[` | a authority_rules id renamed (identity change) |
| `remove_observation_types` | resource | `observation_types[` | a observation_types resource removed |
| `add_observation_types` | resource | `observation_types[` | a observation_types resource added (copy, new id) |
| `rename_observation_types` | resource | `observation_types[` | a observation_types id renamed (identity change) |
| `remove_constraints` | resource | `constraints[` | a constraints resource removed |
| `add_constraints` | resource | `constraints[` | a constraints resource added (copy, new id) |
| `rename_constraints` | resource | `constraints[` | a constraints id renamed (identity change) |
| `object_primary_key` | object_type | `primary_key` | primary_key changed |
| `object_description` | object_type | `description` | description added/changed/removed |
| `object_implements_add` | object_type | `implements` | implements gains an element |
| `object_implements_remove` | object_type | `implements` | implements loses an element |
| `object_implements_change` | object_type | `implements` | implements element changed |
| `property_name` | property | `properties[` | property name changed |
| `property_required` | property | `.required` | property required flipped |
| `property_immutable` | property | `.immutable` | property immutable flipped/added |
| `property_description` | property | `.description` | property description changed |
| `property_constraint_add` | property | `.constraints` | property constraint added |
| `property_constraint_remove` | property | `.constraints` | property constraint removed |
| `property_constraint_change` | property | `.constraints` | property constraint changed |
| `property_add` | property | `properties[` | a property added to some owner |
| `property_remove` | property | `properties[` | a property removed from some owner |
| `type_primitive` | type | `.type|.output` | primitive type changed |
| `type_ref_target` | type | `.type|.output` | ref target changed |
| `type_wrap_optional` | type | `.type|.output` | type wrapped in optional |
| `type_wrap_list` | type | `.type|.output` | type wrapped in list |
| `type_unwrap` | type | `.type|.output` | list/optional constructor removed |
| `type_ctor_swap` | type | `.type|.output` | list <-> optional |
| `type_primitive_to_ref` | type | `.type|.output` | primitive replaced by a ref |
| `link_from` | link_type | `from` | link from changed |
| `link_to` | link_type | `to` | link to changed |
| `link_directed` | link_type | `directed` | link directed flipped |
| `from_cardinality_min` | link_type | `from_cardinality.min` | from_cardinality min changed |
| `from_cardinality_max` | link_type | `from_cardinality.max` | from_cardinality max changed (1 / n / '*') |
| `to_cardinality_min` | link_type | `to_cardinality.min` | to_cardinality min changed |
| `to_cardinality_max` | link_type | `to_cardinality.max` | to_cardinality max changed (1 / n / '*') |
| `cardinality_one_vs_star` | link_type | `to_cardinality.max` | max 1 <-> '*' |
| `interface_required_link_add` | interface | `required_links` | required_links gains an element |
| `interface_required_link_remove` | interface | `required_links` | required_links loses an element |
| `interface_capability_add` | interface | `capabilities` | capability added |
| `interface_capability_change` | interface | `capabilities` | capability changed |
| `policy_decision` | policy | `decision` | policy decision changed |
| `policy_expression` | policy | `expression_ref` | policy expression_ref changed |
| `policy_version` | policy | `version` | policy version changed |
| `authority_principal` | authority_rule | `principal_selector` | principal_selector changed |
| `authority_capability` | authority_rule | `capability` | capability changed |
| `authority_resource` | authority_rule | `resource_selector` | resource_selector changed |
| `authority_effect` | authority_rule | `effect` | authority effect allow <-> deny |
| `authority_delegation` | authority_rule | `delegation_allowed` | delegation_allowed flipped/added |
| `observation_subject` | observation_type | `subject_type` | subject_type changed |
| `observation_source` | observation_type | `source_binding` | source_binding changed |
| `constraint_scope` | constraint | `scope` | scope changed |
| `constraint_expression` | constraint | `expression_ref` | expression_ref changed |
| `constraint_severity` | constraint | `severity` | constraint severity hard <-> soft |
| `function_input_add` | function | `inputs` | function input appended |
| `function_input_remove` | function | `inputs` | function input removed |
| `function_input_swap` | function | `inputs` | function first two inputs swapped (order is significant) |
| `function_input_required` | function | `required` | function input required flipped |
| `action_input_add` | action | `inputs` | action input appended |
| `action_input_remove` | action | `inputs` | action input removed |
| `action_input_swap` | action | `inputs` | action first two inputs swapped (order is significant) |
| `action_input_required` | action | `required` | action input required flipped |
| `function_reads_add` | function | `reads` | function reads gains an element |
| `function_reads_remove` | function | `reads` | function reads loses an element |
| `function_reads_change` | function | `reads` | function reads element changed |
| `function_implementation` | function | `implementation_ref` | implementation_ref changed |
| `function_determinism` | function | `determinism` | determinism changed/added |
| `kind_function_to_action` | kind | `functions[` | a Function re-declared as an Action of the same id |
| `kind_action_to_function` | kind | `actions[` | an Action re-declared as a Function of the same id |
| `action_authority_refs_add` | action | `authority_refs` | action authority_refs gains an element |
| `action_authority_refs_remove` | action | `authority_refs` | action authority_refs loses an element |
| `action_authority_refs_change` | action | `authority_refs` | action authority_refs element changed |
| `action_policy_refs_add` | action | `policy_refs` | action policy_refs gains an element |
| `action_policy_refs_remove` | action | `policy_refs` | action policy_refs loses an element |
| `action_policy_refs_change` | action | `policy_refs` | action policy_refs element changed |
| `action_preconditions_add` | action | `preconditions` | action preconditions gains an element |
| `action_preconditions_remove` | action | `preconditions` | action preconditions loses an element |
| `action_preconditions_change` | action | `preconditions` | action preconditions element changed |
| `action_idempotency` | action | `idempotency` | idempotency changed |
| `action_outcome_predicate` | action | `outcome_predicate` | outcome_predicate changed |
| `action_version` | action | `version` | action version changed |
| `action_compensation` | action | `compensation_action` | compensation_action absent->null->'zz'->null |
| `action_effect_add` | action | `effects` | effect appended |
| `action_effect_rm` | action | `effects` | effect removed |
| `action_effect_swap` | action | `effects` | first two effects swapped (order is significant) |
| `action_effect_op` | action | `effects` | effect operation changed |
| `action_effect_target` | action | `effects` | effect target changed |
| `action_effect_fields` | action | `effects` | effect fields extended |
| `set_list_duplicate` | set_list | `implements|required_links|capabilities|reads|authority_refs|policy_refs|preconditions|constraints|fields|imports` | an element of a set-valued list duplicated (duplicates are kept) |
| `cardinality_star_vs_large_int` | link_type | `cardinality.max` | max '*' -> 1000000 |

115 classes.

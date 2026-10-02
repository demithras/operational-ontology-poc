# Manufacturing logic bindings: provenance

Every behavioural string of `ir.json` is bound in `domains/manufacturing/logic/` (47 required items: 44 logic bindings + 3 adapter targets, 0 unbound;
`tests/domains/test_binding_coverage.py`). Logic receives a read-only view and returns values/booleans only; the
Engine owns when it runs and how results combine (authority, policy order, approval, idempotency, outcome).

## Where each part is ported from (this repo, the v1 POC)

| IR namespace | module | v1 source | check |
|---|---|---|---|
| function `available_quantity`, `incoming_before`, `work_order_risk` | `logic/functions.py`, `logic/facts.py` | `reference_model/state.py`, `reference_model/derive.py` | `test_risk_matches_reference_model_on_seed_and_after_delay_recovery` runs the v1 module and compares |
| function `recommend_transfer`, `recommend_transfer_for_work_order` | `logic/functions.py` | `services/decision_service/planner` | `test_recommend_transfer_for_at_risk_work_order_and_none_otherwise` |
| function `resolve_canonical_id`, decision content hash | `logic/functions.py` | `reference_model/transitions.py:resolve_id`, `services/decision_service/hashing.py` | `test_decision_content_hash_equals_v1_hashing_module`, `test_resolve_canonical_id_maps_and_passes_through` |
| policy expressions | `logic/policies.py` | `contracts/policies/v2/*.rego` (one shared `decision` per rego package; the three IR policies of an action are views of it) | `test_constants_match_v1_sources`, e2e deny/approval tests |
| constraints | `logic/constraints.py` | `contracts/shapes/v3/*.ttl`, `reference_model` invariants | e2e negative-path matrix |
| preconditions, outcome predicates, payloads | `logic/actions.py` | `contracts/actions/v3/*.yaml` (preconditions, closure/outcome), `contracts/reconciliation` | `test_manufacturing_e2e.py` |
| numbers (thresholds, safety stock, freshness) | `logic/data.py` | `contracts/policies/v2/data.json`, `contracts/actions/v3/transfer_inventory.yaml`, `contracts/actions/v1/expedite_purchase_order.yaml` | `test_constants_match_v1_sources` re-reads those files |

Adapters (`adapters/wms_fake.py`, `erp_mes_fake.py`) are in-process fakes limited to the H20 allowlist: translate an
approved effect, return the raw response, emit CDC-like observations (modes `ok|reject|partial|wrong_quantity|timeout|
commit_no_response`, `cdc_visible`). They keep no authority, policy, precondition, idempotency or provenance logic.
The WMS keys a transfer by execution id like a real one, so a repeated call never moves stock twice.

## principal_selector (risk raised in the P4a review) -> RESOLVED BY EVIDENCE: no binding is needed or possible

`expedite_purchase_order` and `reschedule_work_order` list `authority_refs` whose rules are
`transfer-inventory-planner|junior-planner|agent-grant` (capability `action:transfer_inventory`) and
`approve-large-transfer-supervisor` (capability `approval:large_transfer_v1`). `warehouse#<rel>` is in the Engine
grammar (resolvable type), so `required_bindings` asks for no `principal_selector` binding at all. The pipeline asks for
capability `action:expedite_purchase_order`; no listed rule has it, so the authority gate has `allow == []` for every
principal (checked for planner, junior, supervisor, senior approver and the delegated agent:
`test_expedite_and_reschedule_cannot_pass_authority_on_the_frozen_ir`). A `principal_selector` binding is never
consulted because it is only called for selectors outside the grammar. The v1 authorization model
(`contracts/authorization/v2/model.fga`) binds `can_transfer_inventory` to the warehouse object; for these two actions
there is no warehouse input to bind, so deriving one from the work order / purchase order would mean authorizing under a
capability the IR does not grant. I did not invent that derivation: it would be a guessed authority decision inside
domain logic, which the preregistration forbids. The logic for both actions (preconditions, policy, payloads, outcome)
IS bound and works once the IR grants the capability: `test_expedite_and_reschedule_logic_works_once_the_ir_authorizes_them`
runs it on a TEST-ONLY patched IR (one extra allow rule per action). Fixing the frozen `domains/manufacturing/ir.json`
is outside this phase (read-only): see "Protocol concerns" in the P4b report.

## DEVIATION: ADR-0003 high-priority protection is an authority fact evaluated inside a deny policy

`transfer_inventory` lists `auth:mitigate-high-priority-planner|supervisor` in `authority_refs`. In v1 the protection is
an AND (can_transfer_inventory AND, for a protected route, can_mitigate_high_priority). The Engine's authority gate
(section 5 of docs/engine_semantics.md) requests only `action:transfer_inventory` and ORs the allow rules, so the
`action:mitigate_high_priority` rules are never requested and the conjunction cannot be expressed with the frozen IR and
the unchanged Engine. To keep the v1 behaviour (a junior planner is denied on a transfer that protects a fresh HIGH
priority at-risk work order; planner and supervisor pass) `policies._protection_denies` reads the principal's Warehouse
relations. It returns a boolean and the Engine still combines it (deny > require_approval > allow), but it IS an authority
decision living in domain logic, against the P4b brief ("must not perform authority decisions themselves"). Not fixable
without an Engine/IR change (e.g. per-action required capabilities as AND); reported under "Protocol concerns".
`test_high_priority_protection_denies_junior_but_not_planner` and `test_protection_control_same_route_not_high_priority_junior_allowed`
(control: same route, work order not HIGH) pin it.

## Synthetic data

`seed.json` is generated by `scripts/build_mfg_seed.py` (canonical-incident shape of `seed/fixtures/canonical_incident.yaml`
plus a bulk part PX-900 so large unprotected transfers exist). Principals: planner-1, junior-1, supervisor-1, senior-1,
agent-1 (delegated by planner-1), agent-orphan (delegator holds no relation). Synthetic, not production data.

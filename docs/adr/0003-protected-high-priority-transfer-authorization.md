# ADR 0003 — Protected high-priority transfer authorization (Phase 6 step 0)

**Status:** accepted (amended same day — see "Security review amendment" below)
**Date:** 2026-09-24

## Context

An orchestrator review of Phase 5 found `docs/experiment/spec/03_domain_scenario.md`'s
canonical negative case —

```text
Unauthorized actor: junior user attempts protected transfer
-> authorization = DENY, external_effects = 0
```

— was untestable as built. `contracts/authorization/v1/model.fga` unions
`junior_planner` into `can_transfer_inventory` (correctly, per
`03_domain_scenario.md`: "junior_planner: can propose"), so junior-1 is
authorized for ANY `transfer_inventory` proposal within its region,
regardless of what the transfer is FOR. Verified live against the running
Phase 5 stack: `junior-1` proposing a 20-unit WH-B->WH-A transfer returned
`APPROVED`. `03_domain_scenario.md`'s own authorization example distinguishes
"can propose" from "can execute <= 100 units in assigned region" for
`planner`, but says nothing that singles out a HIGH-priority-work-order
mitigation as junior's one forbidden case — that distinction has to be
introduced somewhere, and the natural reading of "protected transfer" in the
canonical scenario is exactly this: transfers proposed to resolve WO-42
(`priority: HIGH`) are more consequential than routine rebalancing, and
committing to one is a decision junior should not be able to make alone.

## Decision

1. `transfer_inventory` v1 (`contracts/actions/v1/transfer_inventory.yaml`)
   gains an OPTIONAL formal parameter, `work_order` — a promotion of the
   pre-existing `context.work_order_id` (informational-only, used solely to
   attach the `linked_work_order_risk` evidence fact) to a real ActionType
   parameter. This matters because `parameters` (unlike `context`) is
   covered by `decision_content_hash`
   (`services/decision_service/hashing.py::decision_content_hash`) — once a
   value is going to gate authorization, it must be part of the immutable,
   hash-pinned tuple F33 (approval-replay-on-changed-decision) protects,
   not a side channel that could be swapped after evidence/authz/policy
   already ran against a different one. `context.work_order_id` remains
   accepted for backward compatibility (informational only, unchanged
   behavior) — `evidence.py` prefers `parameters.work_order` and falls back
   to it.
2. `contracts/authorization/v1/model.fga`'s `warehouse` type gains a new
   relation, `can_mitigate_high_priority: planner or supervisor` — the same
   shape as the existing `can_approve_large_transfer: supervisor` split
   (junior_planner deliberately excluded), reusing the SAME object
   (`source_warehouse`, via `services/decision_service/authz.py::resolve_object`,
   unchanged) that `can_transfer_inventory` is already checked against.
3. `services/decision_service/evidence.py` folds the linked work order's
   `priority` (LOW|MEDIUM|HIGH) into the existing `linked_work_order_risk`
   evidence fact — see the "Security review amendment" below for where this
   now comes from and why.
4. `services/decision_service/propose_flow.py` runs a SECOND authorization
   check — `authz.check_high_priority_protection` — immediately after the
   base `can_transfer_inventory` check ALLOWS, but only when the proposal is
   determined to be `route_protected` (see the amendment below). A deny here
   overwrites `record.authz_result` (there is exactly one authorization
   verdict per decision, matching every other ActionType) and the decision
   terminates `DENIED_AUTHORIZATION` with zero external effects, identically
   to a base-check deny.

Net effect exactly matches the orchestrator's acceptance list: junior-1
proposing a transfer for WO-42 (HIGH) -> `DENIED_AUTHORIZATION`, 0 effects;
junior-1 proposing a transfer with no linked work order (or one that isn't
HIGH) -> allowed, unchanged from Phase 5; planner-1 for WO-42 -> allowed.
`services/decision_service/planner.py` (H10's deterministic planner) now
submits `parameters.work_order` for its own canonical recommendation, so the
system's own automated mitigation path is never itself protected-transfer-blocked
for the planner-1/supervisor-1 actors it is meant to run as.

## Alternatives considered

- **New `work_order` FGA type with its own `planner`/`supervisor`/`in_region`
  relations** (the brief's own illustrative example). Rejected: Phase 5
  already established, and documented
  (`docs/experiment/implementation-notes.md`: "`resolve_object` is the
  pattern for binding any FUTURE ActionType to the existing warehouse-scoped
  authorization model without new FGA types"), that this authorization model
  has exactly one typed authority object (`warehouse`) and deliberately
  resolves `purchase_order`/`work_order`-scoped actions onto it rather than
  minting new types. A `work_order` FGA type would need its own region/
  authority tuples synchronized from MES data (a new sync mechanism, not
  just a new check) for a distinction (planner/supervisor vs junior) that
  the warehouse type already expresses today.
- **OpenFGA conditions (CEL expressions) keyed on work-order priority**.
  Rejected: conditions would let OpenFGA itself evaluate "is this work order
  HIGH priority", but that fact is sourced from MES via the decision
  service's own evidence pipeline (closed-world closure, freshness,
  MES-unreachable-fails-open semantics) — duplicating that logic into a CEL
  expression evaluated inside OpenFGA would create a second, harder-to-audit
  copy of the same evidence-resolution rule, contrary to
  `05_ontology_and_contracts.md`'s "each rule has one canonical owner"
  principle. The chosen design keeps evidence resolution entirely in
  `evidence.py` (one owner) and OpenFGA's job exactly what it already is
  elsewhere in this repo: "does this actor+relation+object triple hold".
- **Contextual tuples per check** (pass a transient
  `{work_order}#priority_high` tuple with the Check call). Rejected as
  unnecessary complexity once the object being checked is still just
  `warehouse:<source_warehouse>` — the HIGH-priority condition never needs
  to be represented as an OpenFGA tuple/relation on the work order at all;
  it only needs to gate WHETHER `check_high_priority_protection` runs a
  second check, which a plain Python `if` does with zero OpenFGA-side
  moving parts.

## Consequences

- `contracts/authorization/v1/model.fga`'s content-addressed
  `authorization_model_version` changes for every decision proposed from
  this commit onward (expected and correct — the model genuinely changed).
- `linked_work_order_risk`'s evidence fact now costs one extra MES REST call
  per proposal that links a work order (negligible next to the OpenFGA/OPA/
  RDF4J round trips already measured in `tests/performance/bench_phase5.py`).
- See the "Security review amendment" below for the final (fail-closed,
  non-bypassable) failure-mode design — superseding this ADR's original
  fail-open MES-unreachable posture.
- `contracts/authorization/v1/tests.yaml` gains two new cases (5 new checks):
  `junior-denied-protected-high-priority-mitigation` and
  `planner-and-supervisor-allowed-protected-high-priority-mitigation`.
  `tests/integration/test_decision_service_protected_transfer.py` proves the
  same split end-to-end through the real HTTP API against a real, currently
  at-risk HIGH-priority work order in the seeded dataset (see the amendment
  below for why the test does not hard-code WO-42 specifically), never
  mutating any MES row.

## Security review amendment (same day)

An independent security review of this ADR's original design found two
gaps before it shipped:

1. **Fail-open on unresolvable priority.** The original design fetched
   `priority` live from MES inside `evidence.py` and treated MES-unreachable/
   404 as `priority=None` -> "not protected" -> the proposal proceeds as an
   ORDINARY (unprotected) transfer. That is backwards for a security gate:
   an attacker (or a routine MES blip) could make the one fact this
   protection depends on simply unavailable and the system would silently
   fall back to the LESS restrictive path. Every other gate in this
   architecture fails closed on an unresolvable dependency (F08 stale
   evidence, F23 OpenFGA unavailable, F24 OPA unavailable) — this one must
   too.
2. **Caller-declared bypass.** Because the original design read
   `parameters.work_order`/`context.work_order_id` to decide whether
   protection applies AT ALL, a caller could simply OMIT `work_order` on a
   transfer that, in fact, fully mitigates WO-42 (or any other HIGH-priority
   at-risk work order) and reach `APPROVED` as junior-1 exactly as before
   this ADR — the protection existed only for callers honest enough to
   declare it.

**Fix, both closing the same root cause** (protection status must be a
SERVER-DERIVED fact, never a caller-supplied one, and "cannot determine" must
mean "deny", never "allow"):

- **Source of truth moved to the hot projection, not a live MES call.**
  `contracts/projections/v1/work_order_risk.yaml`'s `work_orders` SPARQL
  query now also selects `fac:priority`; `services/projection_builder/compute.py`'s
  `WorkOrderRiskRow` carries it through unchanged (never computed — a
  straight pass-through of an MES-sourced RDF fact, same treatment as
  `severity` is a COMPUTED field vs. this being a PASSED-THROUGH one);
  `work_order_risk`'s schema/hashing/writer gained the column
  (`services/projection_builder/schema.sql` — including an idempotent
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for a stack already running
  from an earlier phase, since `CREATE TABLE IF NOT EXISTS` alone is a
  no-op against an existing table). `priority` now has the SAME
  freshness/provenance treatment as every other hot-projection fact, instead
  of being the one gate input read through a separate, ungoverned side
  channel.
- **`services/decision_service/evidence.py::_resolve_route_protection`**
  is the new, server-side, non-bypassable determination: it looks up
  `transfer_candidates` (Phase 4's own "is this (part, source_warehouse,
  destination_warehouse) a real mitigation route for some at-risk work
  order" projection — `services/projection_builder/reader.py::get_transfer_candidates_for_route`,
  new) for the EXACT route the caller proposed, entirely independent of
  whatever `work_order` value (if any) was declared. For every matching
  work order it resolves `priority`+`at_risk` from `work_order_risk`,
  requiring `min(the MES ingestion watermark, that row's own computed_at)`
  to be within `max_evidence_freshness_s` — the same watermark pattern
  Phase 5's own fix established for inventory freshness
  (`_resolve_source_inventory_with_freshness`), scoped here to the one
  source system (`MES`) `fac:priority` is authoritative for. Three outcomes:
  `NOT_APPLICABLE` (route matches no work order at all — the ordinary case,
  costs nothing extra), `UNRESOLVED` (matches, but freshness/priority could
  not be verified -> **`INSUFFICIENT_EVIDENCE`, 0 effects, for every actor**,
  computed BEFORE authorization ever runs), or a resolved `PROTECTED`/
  `UNPROTECTED` verdict that `authz.check_high_priority_protection` (Phase 6
  step 0's original design, unchanged) gates the second OpenFGA check on.
- **Honesty check, not a security backstop**: if a caller explicitly
  declares a `work_order` that IS currently real and at-risk but does not
  correspond to a `transfer_candidates` row for the exact route proposed,
  the proposal is rejected `INSUFFICIENT_EVIDENCE` (`work_order_route_mismatch`)
  — the declaration and the route disagree. This is deliberately NOT the
  mechanism that decides whether protection applies (that is
  `_resolve_route_protection` alone, unconditionally) — it exists only so a
  caller cannot attach a misleading/irrelevant work order claim to a
  decision's permanent evidence record.
- Ordinary transfers (no work order anywhere near the route) pay ZERO extra
  cost: `get_transfer_candidates_for_route` returns empty, `NOT_APPLICABLE`
  is returned immediately, and no MES-watermark lookup or extra freshness
  check happens at all — verified by every pre-existing decision-service
  test (F01-F09, gates, policy, canonical, delegation, approval, forensic),
  which all use synthetic parts with zero `transfer_candidates` rows and
  pass unchanged.
- `tests/integration/test_decision_service_protected_transfer.py` discovers
  a real HIGH-priority, currently-at-risk work order from the LIVE hot
  projection at test time (preferring WO-42, falling back to any other
  seeded one, skipping with an explicit reason if none exists) rather than
  hard-coding WO-42 — `tests/integration/test_canonical_scenario.py`
  (Phase 2) permanently mitigates WO-42 the first time the full suite runs
  it (documented in `tests/integration/decision_helpers.py`'s own module
  docstring), so a test hard-coded to WO-42 would pass in isolation and fail
  as part of `make test`'s full run depending on file collection order.

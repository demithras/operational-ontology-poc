# ADR 0004 — Historical authorization replay: model id, not a tuple snapshot per decision

**Status:** accepted
**Date:** 2026-09-24

## Context

`docs/experiment/spec/14_risks_and_open_questions.md` R4 asks:

> Should replay prove that the actor *was authorized according to
> historical model + historical relationship tuples*, or only record the
> historical authorization result?
>
> Strong replay requires historical tuples/context too.
>
> **POC decision:** preserve enough authorization input/relationship
> snapshot or immutable result evidence to independently reproduce
> selected authorization cases. This deserves an ADR during implementation.

Phase 7 needed a concrete answer before building `services/decision_service/replay.py`.

## Decision

**Model, yes — full relationship-tuple snapshot per decision, no.**

Every `Decision` now records the REAL OpenFGA `authorization_model_id`
(`contracts/ontology/v1/oo-core.ttl`'s `oo:openfgaAuthorizationModelId`,
distinct from the existing content-hash `oo:authorizationModelVersion`) via
`services/decision_service/authz.py::resolve_latest_authorization_model_id`,
resolved fresh per propose() request (never cached — a redeploy must take
effect on the very next request, same policy as `_current_store_id`).
Every gate-result resource (`oo:AuthorizationCheck`) also records
`oo:checkAuthorizationModelId` for that specific check.

Replay re-issues the IDENTICAL `Check` request — same `relation`, same
`object`, same `user`, same `authorization_model_id` — against the LIVE
OpenFGA server and compares the outcome to what was recorded. This works
because:

- **OpenFGA models are immutable by id and additive.** Publishing a new
  model version (`migrations/v2_to_v3/migrate_authz.py`) never edits or
  deletes an older one — every model this experiment has ever written
  stays resolvable in the SAME store, forever, by its own id.
- **We do not snapshot relationship tuples per decision.** Tuples
  (`can_transfer_inventory`, `supervisor`, `senior_approver`, ...) are
  live, mutable, cross-cutting state — copying them into every Decision's
  own RDF graph would mean re-implementing OpenFGA's own relationship
  graph inside this codebase's evidence model, for no proven benefit: this
  experiment's authorization changes are MODEL changes (new/renamed
  relations), never a tuple being silently deleted out from under a
  decision the moment after it was made. `migrations/*/migrate_authz.py`
  is itself an explicit, auditable step (`migration.json` fixtures,
  `scripts/compat_check.py`) — the same discipline this repo already
  applies to ontology/policy changes.

## Consequence — the one real gap, stated plainly

If a FUTURE change ever deletes/mutates a relationship tuple in place
(rather than publishing a new model), a decision's replayed authorization
check would reflect the CURRENT tuple state, not the tuple state AT
PROPOSAL TIME — this is the weaker form R4 names as the fallback
("or only record the historical authorization result"). Replay's
`gate_result_match` therefore always ALSO compares against the recorded
`oo:checkOutcome` as the authoritative record, and
`services/decision_service/replay.py` labels which mode it used
(`authz_replay_mode: "live"` when the live re-Check ran; the OpenFGA store
using the `memory` datastore engine, wiped on container restart, is the
one scenario this repo cannot protect against without moving OpenFGA to
persistent storage — out of scope for this POC, called out honestly rather
than silently papered over).

## Why not option 2 (record the historical result only, never re-Check)

Rejected as the PRIMARY mechanism (though it is the fallback, see above):
it would make `gate_result_match` trivially true by construction (comparing
a recorded value to itself proves nothing about reproducibility) and
defeats H7's actual claim ("a decision can be reconstructed using the
versions... that existed at decision time" — reconstruction, not
recitation).

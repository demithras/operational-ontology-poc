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

## Consequence — the one real gap, stated plainly (CLOSED — see update below)

If a FUTURE change ever deletes/mutates a relationship tuple in place
(rather than publishing a new model), a decision's replayed authorization
check would reflect the CURRENT tuple state, not the tuple state AT
PROPOSAL TIME — this is the weaker form R4 names as the fallback
("or only record the historical authorization result"). Replay's
`gate_result_match` therefore always ALSO compares against the recorded
`oo:checkOutcome` as the authoritative record, and
`services/decision_service/replay.py` labels which mode it used
(`authz_replay_mode: "live"` when the live re-Check ran).

**Update, same day**: the "memory datastore, wiped on restart" gap
originally called out here as out-of-scope stopped being theoretical
almost immediately — this repo's OWN `tests/integration/test_decision_service_dependency_outage.py`
(F22-F26, real `docker compose stop/start` against rdf4j/openfga/opa/
projection_builder) restarts the real `openfga` container as part of F23,
and the `memory`-engine store's wipe there SILENTLY REGRESSED a later,
unrelated test in the same `make test` session (an approval check that
should 200 instead 403'd, because F23's own rebootstrap-on-restart helper
only restored the V1 authorization model, never migrate_authz.py's V2
one). That is not a hypothetical FUTURE change — it is this experiment's
OWN outage-test suite exercising the documented gap on every `make test`
run.

**Fixed**: OpenFGA now runs on the `postgres` datastore engine (its own
database, `docker-compose.yml`'s `openfga-migrate` one-shot service runs
`openfga migrate` before `openfga` starts) instead of `memory` — a
container restart no longer loses the store, its models, or its tuples,
period; `tests/faults/test_openfga_persistence.py` proves this directly
(real restart, same store id, same latest model id, an existing approval
check still 200, a real V1 corpus decision still replays PASS).
`services/decision_service/bootstrap_openfga.py::_write_model` is also now
content-aware idempotent (compares the new model's normalized
`type_definitions` against every model the store already has, reusing an
existing id when unchanged) so repeated `make up`/bootstrap invocations no
longer churn `contracts/manifests/openfga_model_ids.json` for no reason.
`authz_replay_mode: "recorded_only"` remains the correct, honest fallback
for any decision whose authorization_model_id predates this fix (this
session's own historical corpus — see docs/experiment/implementation-notes.md
Phase 7 section) or for the (now much narrower) case of a genuine in-place
tuple mutation, which this change does not and cannot address.

## Why not option 2 (record the historical result only, never re-Check)

Rejected as the PRIMARY mechanism (though it is the fallback, see above):
it would make `gate_result_match` trivially true by construction (comparing
a recorded value to itself proves nothing about reproducibility) and
defeats H7's actual claim ("a decision can be reconstructed using the
versions... that existed at decision time" — reconstruction, not
recitation).

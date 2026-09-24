# ADR 0004 — Historical authorization replay: model id, not a tuple snapshot per decision

**Status:** accepted, SUPERSEDED IN PART by the "Update (Phase 7b)" section
below — this ADR's title and original Decision below now describe what
Phase 7 built; Phase 7b added the whole-store tuple snapshot the original
Decision explicitly declined, once the orchestrator's independent
replay verification found the undeclined alternative (recorded_only
result, never re-proven) was silently the norm for the ENTIRE corpus.
Read the Context/Decision/Consequence below for the original reasoning,
then the Phase 7b update for what changed and why.

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

## Update (Phase 7b) — the tuple snapshot the original Decision declined

The orchestrator's independent verification of Phase 7 (tag
`poc-v0.7-replay`) found that replaying the entire 232-decision live
corpus reported PASS for all 232, but `authz_replay_mode ==
"recorded_only"` for 232/232 — i.e. **zero** decisions in the acceptance
corpus ever actually re-proved authorization; every one used the fallback
this ADR calls "the weaker form" and "not the PRIMARY mechanism". The
proximate cause was the real `memory`-datastore incident this ADR already
documents above (their original model ids stopped resolving). But the
deeper problem is structural, not incidental: `gate_result_match` treats
`recorded_only` and `live` identically when computing `status: PASS`, so
this failure mode is invisible in the corpus's own headline number, in
direct tension with H7's "reconstruction, not recitation" claim two
paragraphs up. Silently keeping PASS whenever the live check is
UNAVAILABLE is fail-open replay — the opposite of F29's "old artifact
missing -> replay fails loudly" design intent applied to authorization
specifically.

**Revised decision: capture the tuple snapshot after all — but the WHOLE
store's tuples, not a per-decision derived subset.** The original
rejection of tuple-snapshotting argued it would mean "re-implementing
OpenFGA's own relationship graph inside this codebase's evidence model,
for no proven benefit" — true of a subset-computing scheme that tries to
infer which tuples were *relevant* to one Check's graph traversal (that
really would require reimplementing OpenFGA's own resolution algorithm).
It is not true of a **whole-store snapshot**: this experiment's real
authorization model has on the order of 10 tuples
(`contracts/authorization/v1/tuples.yaml` /
`contracts/authorization/v2/tuples.yaml`), so `authz.py::_read_all_tuples`
reads the entire store via `POST .../read` (paginated, though one page
always suffices here) on every `authz.check()` call and stores the result,
canonicalized, as `AuthzResult.tuples_snapshot` ->
`oo:checkTuplesSnapshotJson` on the `oo:AuthorizationCheck` resource. No
second store, no re-implemented graph — just the plain tuple list R4
itself offered as the fallback design ("or the whole small tuple set
hashed").

Replay (`services/decision_service/replay.py::replay_decision`) now
passes that snapshot back to `authz.check()` as OpenFGA's own
**`contextual_tuples`** field — tuples considered for that one Check call
only, never written to the store. This means replay proves authorization
against the tuple state that existed AT PROPOSAL TIME even if the live
store's tuples have since drifted (the narrower future-gap this ADR's
original Consequence section left open), without restoring anything or
needing a second store.

`authz_replay_mode` gains a real teeth: `ReplayResult.status` is no longer
just `PASS`/`FAIL` — a decision that reaches all the way through
evidence/action/policy reconstruction but can only fall back to
`recorded_only` now reports `PARTIAL_RECORDED_ONLY`, a distinct, explicit,
separately-counted status, never folded into `PASS`. A decision that never
reached an authorization check at all (`INSUFFICIENT_EVIDENCE`) reports
`authz_replay_mode: "not_applicable"` instead — there is nothing to
replay, which is a different (and unproblematic) thing from "couldn't
replay it". `tests/replay/test_replay_corpus.py` now asserts
`authz_replay_mode == "live"` for every corpus decision that has an
authorization check at all — 100%, not merely "PASS on the corpus". A new
F29-style test (`tests/replay/test_f29_tuple_snapshot_integrity.py`)
tampers with a real decision's `oo:checkTuplesSnapshotJson` (removing the
tuple that actually grants the recorded outcome) and proves replay goes
from PASS to FAIL, not a silent pass-through — the tuple snapshot is
exercised, not merely stored.

Cost: one extra small (~10-row) HTTP read per `authz.check()` call,
best-effort (a failed read degrades that decision to the pre-existing
`recorded_only` fallback, never a hard error at propose time) — negligible
against this model's size, and the ENTIRE reason option 2 above was
rejected as a primary mechanism no longer applies once the snapshot is
real and gets replayed against, not merely stored and cited.

**Found live while wiring this up**: OpenFGA validates every
`contextual_tuples` entry against the PINNED `authorization_model_id`'s own
schema, not the store's latest model. A whole-store snapshot captured NOW
can contain a tuple for a relation that did not exist yet in an OLDER
model — this experiment's real case: `senior_approver`
(`migrations/v2_to_v3/migrate_authz.py`) is absent from the v1 model's
`region` type, so replaying ANY v1-era decision with the unfiltered
current snapshot made OpenFGA reject the WHOLE Check with HTTP 400
("relation ... not found"), which `authz.check()` correctly reported as
`UNAVAILABLE` — the honest failure mode, but it meant every v1-era
decision silently fell back to `recorded_only` again, defeating the whole
point. Fixed in `authz.py::_filter_tuples_for_model` (cached per model id,
immutable): before sending `contextual_tuples`, keep only the tuples whose
(object type, relation) pair the TARGET historical model actually defines.
This is not a workaround — it is exactly correct: a historical model could
never have resolved a relation it didn't know about either, so dropping
those tuples changes nothing about what that model's own Check would have
returned at proposal time.

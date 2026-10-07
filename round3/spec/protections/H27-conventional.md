# H27 protections - conventional variant (append-only content-addressed audit log + shared anchor)

Paths relative to `round3/src/conventional/`; line numbers at the commit tagged `r3-g2-conventional`. The audit-log writer is
service middleware and is counted as OUR code (EQUIVALENCE-G2). All durable records other than the world store live in the
HistoryStore when `history` is given (`HISTORY_LAYOUT`, `histledger.py:18`); H23/H24 behaviour is unchanged when it is None.

| Id | Where | Mechanism |
|---|---|---|
| Envelope + chain (s2) | `provenance.py:120` (`finalize`) | Frozen envelope `{v, stream, seq, prev, decision, artifacts}` in `r3_shared.evidence.canonical_bytes`; seq/prev are taken from the anchor's head (the anchor, not the mutable store, is the authority on the chain); `root = sha256(canonical(envelope))`. |
| Evidence set (s1) | `provenance.py:91` (`collect`), called inside the commit transaction at `service.py:293` | Every resource-typed input (absent -> `{"ref","absent":true}`) plus the object each `{"newest": ...}` term selects (max integer field; ties keep the first key). `unique`/`exists` objects are NOT bound (Q6). Floats -> INVALID `float_in_artifact` (`service.py`, before commit). |
| Anchor before ack (R27-6) | `provenance.py:151-153` (`anchor.append` then store receipt/envelope), `service.py:209` (`_provenance`), `service.py:309` / `authority_ops.py:113` (retry of a committed id without an anchor entry -> UNAVAILABLE) | The result is returned only after `AnchorClient.append`; an `AnchorError` yields UNAVAILABLE `anchor_unavailable` even though the world transaction committed (replay: UNRESOLVED `unanchored`, `replay.py:58`). |
| Replay (s6, R27-1/2/3/7) | `replay.py:77` (`_replay`), `replay.py:106` (`_blob`), `replay.py:138` (`_authority_check`), `variant.py` (`replay`, `explain` share one code path) | Fresh deployment, anchor lookup of (stream, decision_id) -> seq; for m = seq..1: envelope bytes must hash to the anchor root, be canonical, carry the right seq/stream and `prev` = anchor root(m-1); every bound artifact is fetched by digest (missing -> UNRESOLVED `missing_artifact`, hash mismatch -> TAMPERED); the authority decision is re-evaluated over the bound authority artifact with the PDP (`pdp.py:29`). No current spec/world is consulted. |
| Continuation (R27-5) | `histledger.py:50` (`idem_get`), `histledger.py:73` (`approvals_open`), `service.py:302-312` | WHETHER a request/approval exists is read from the world log (`commit`, `approval`, `approval_used` marks written in the effect's own transaction); the HistoryStore copy must agree, else `LedgerUnresolved` -> UNAVAILABLE `history_unresolved`, zero effects. A deleted/rewritten idempotency record never yields a second effect; a forged approval record without a world mark is ignored. |
| Clean histories (R27-4) | `tests/conventional/test_conv_g2_h27.py` | untampered histories replay VERIFIED with artifacts digest-equal to the hand-written expected binding. |

`HISTORY_LAYOUT` (declared in `histledger.py:18`, class attribute on the Deployment): `envelope env/`, `receipt receipt/`, `artifact art/` (evidence, authority versions, policy, contract, all by sha256), `approval approval/`, `idempotency ledger/`, `meta meta/` (stream id, initial authority pointer), `evidence_index evref/` (latest digest per ref, used only by replay's evidence_rebinding mutant), `policy_side side/` (digest_omission mutant only).

## Mutant sites

| Mutant | Site | Bug |
|---|---|---|
| `digest_omission` | `provenance.py:147` (writer) + `replay.py:123` (reader) | the policy digest is excluded from the hashed envelope and stored under `side/<seq>`. |
| `fallback_to_current` | `replay.py:109` + `service.py:115` (`current_artifact`) | on a missing historical artifact, replay builds the CURRENT artifact and accepts it if its digest equals the bound one. |
| `evidence_rebinding` | `replay.py:114` | evidence is resolved by `ref` (latest stored version via `evref/`), not by the bound digest, and the digest check is skipped. |
| `receipt_self_trust` | `replay.py:35`, `replay.py:60` | roots/decision ids come from the receipt copies in the HistoryStore, not from the anchor service. |

## Assumptions the frozen text left open (reported to the orchestrator)
1. `effect_digest` = sha256(canonical([world_log rows of the decision's transaction])) with ALL rows of that tx (including the `commit`/`authority` marks) in the `WorldReader.log` row form `{seq,tx,tag,tick,writer,kind,ref,data}`; refusals bind `[]`.
2. `world_seq` of an OK = the seq of the transaction's `commit` mark; refusals bind the log head read after rollback; `tick` of a refusal = `clock.now()`.
3. Decision kinds: `call_tool` (tool surface), `direct`, `approve`, `delegate`, `revoke`; reason code of an OK = `"ok"`; `operation` is the operation name for call_tool/direct/approve and null for delegate/revoke (E-4); `args_digest` = sha256(canonical_bytes(X)), X = the args dict as passed (call_tool/direct), the approved request's args dict (approve, no wrapper), the edge dict (delegate), the edge_id string (revoke). `decision_id` = request_id (approve: `approve-<stream seq>`). `effect_digest` covers all world_log rows of the tx (marks included, all columns, seq order). `newest` ties: greatest value, then smallest ref. Under a v1 authority spec delegate/revoke behave as an empty v2 with max depth 8 (E-3).
4. A request_id-less mutating request gets decision_id `<kind>-<seq>`; approve has no request_id so it always does.
5. Not decisions (no envelope): invalid token, unknown operation, schema INVALID, `idempotency_key_reuse`, an idempotent retry of a committed id, UNAVAILABLE/UNKNOWN.
6. Replay re-evaluates the authority decision only for `call_tool`/`direct`; resources are the bound evidence refs whose type is a resource-typed input of the bound contract (the `newest` object is excluded by type).
7. A stream id is `conventional-<domain>-<128-bit seeded from (domain, history path)>`, persisted in `meta/stream`.

## G2 fix1 (errata E-6, E-7, E-8)

- E-6: after the deny rules, every supplied REQUIRED resource ref must exist at commit, else INVALID `target_not_found`
  (optional refs keep their earlier check). Ordering of the H23 verdicts is unchanged. Sweep: `test_e6_sweep_*` (both domains).
- E-7: `Service.__init__`/`restart()` catch every lineage error (`LedgerUnresolved`, malformed JSON/keys) and set
  `_authority_unresolved`; execute/approve/delegate/revoke/set_authority then refuse (UNAVAILABLE `history_unresolved`, zero
  effects). `HistLedger.authority_get` treats a named-but-missing authority blob as damaged, never fresh. replay/explain
  report TAMPERED/UNRESOLVED from the bound artifacts. Test: `test_e7_*` over write/other-valid-json/delete/rename.
- E-8: governed = valid token + known operation + schema-valid args (from the generated model), whatever the status
  (OK/DENIED/INVALID); `call_tool` on a hidden tool is decided server-side (`_hidden`) and enveloped; replays are not decisions.
  `replay` accepts `tool_not_available` as an authority denial. Test: `test_e8_*` (per kind and status).

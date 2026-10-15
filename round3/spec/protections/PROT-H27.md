# Protection specification H27 - decision provenance is tamper-evident (both variants)

FROZEN 2026-10-07 (author decisions 2026-10-07 #2; rulings in spec/gate2/OPEN-QUESTIONS.md). Requirement-level; the ONE place these rules are written. Attack class A6 (provenance
tamper). Contract: hypotheses/h27/contract.json (frozen). Protocol: PROTOCOL-P1d.md. Author decision 2026-10-06 #4
(trust split) is binding: separate signer process, own key, anchor directory no variant process can write, same anchor
class for both variants.

## 1. Governed decision and its artifacts

A GOVERNED DECISION is every mutating request (call_tool, direct, approve, delegate, revoke) that reaches an authority
or business-rule verdict: status OK, DENIED or INVALID-from-a-precondition/rule. UNAVAILABLE/UNKNOWN and schema
INVALID are not decisions (no envelope). Each decision binds four artifact kinds, each content-addressed
(digest = sha256 of canonical bytes, section 3):
- `evidence`: one artifact per object in the FROZEN EVIDENCE SET of the decision, read inside its commit transaction:
  (i) every resource-typed input, (ii) for every `{"newest": {"type": T, ...}}` term in the operation's business rules
  or preconditions, the object it selects. Form `{"ref": "T:k", "version": n, "props": {...}}`; an absent input is bound
  as `{"ref": "T:k", "absent": true}`. (Objects found by `unique`/`exists` queries are NOT bound; OPEN-QUESTIONS Q6.)
  The oracle reconstructs the same set from world_log at the decision's seq, so the set must be exact.
- `authority`: the authority state in force (H24 v2 document incl. edges/revocations; v1 spec where v2 is unused);
  digest == Deployment.authority_version() at that commit point.
- `policy`: `{"config": ops_spec.config, "business_rules": op.business_rules, "approval": op.approval}` for the operation.
- `contract`: the operation definition minus business_rules/approval, plus the ops spec `helpers` prose and `spec` id.
The decision also binds: decision_id (= request_id; the harness always supplies one), kind (call_tool/direct/approve/
delegate/revoke), subject, on_behalf_of, operation, args_digest (canonical args), status, reason code, effect_digest
(sha256 of the canonical world_log rows the decision's transaction wrote; [] for refusals), world_seq (commit point),
tick, and authority_path (H24 edge ids or []). Refusals write no world transaction; they bind world_seq = the world_log
head read when deciding (H27 histories are generated sequentially, so this is deterministic). approve binds the evidence
set of the approved request; delegate/revoke bind no evidence (authority, policy=null, contract=null digests of `null`).

## 2. Provenance envelope, chain and anchor (frozen)

Envelope (canonical JSON object, every key present, no extra keys):
`{"v": 1, "stream": <deployment stream id>, "seq": n, "prev": <root of seq n-1 or 64*"0">, "decision": {...section 1
scalars...}, "artifacts": {"evidence": [digest...sorted], "authority": d, "policy": d, "contract": d}}`.
`root(n)` = sha256(canonical(envelope n)). seq is gap-free from 1 per stream. A stream = one Deployment lifetime
(`deploy` creates stream `<variant>-<domain>-<uuid-from-seeded-rng>`; restart continues the stream).

ANCHORING is part of the decision: the variant calls `AnchorClient.append(stream, seq, decision_id, root)` and stores
the returned receipt BEFORE returning the decision's result. A decision whose anchor append failed returns UNAVAILABLE
`anchor_unavailable` and, if its world transaction already committed, is reported by replay as UNRESOLVED `unanchored`
(never VERIFIED). The anchor rejects seq != head+1 and a second append for the same (stream, seq).

## 3. Canonical serialization (frozen; changing it after any mutation result => INVALID)

`r3_shared.evidence.canonical_bytes`: json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) UTF-8;
integers as JSON ints, no floats in bound artifacts (a float in a bound artifact is INVALID at decision time),
strings NFC as given (no normalisation), null for absent optional fields. Digests are lowercase hex sha256.

## 4. Trust split (who controls what)

| Component | Trust domain | Attacker access |
|---|---|---|
| World store (canonical effects) | ground truth, meter only reads | none in H27 |
| HistoryStore (r3_shared.histstore, one SQLite file per stream) holding envelopes, receipts, artifact blobs, approvals, idempotency records and every authority/policy/contract version the variant keeps | variant (mutable) | FULL read/write through the tamper interface |
| Variant state_dir / memory | variant | treated as attacker-controlled: replay runs on a FRESH deployment with a NEW empty state_dir (section 6) |
| Anchor service (r3_shared.anchor, separate OS process, own key) | independent | none |
| Oracle expected bindings (harness-side, written before tampering, hashed into the envelope) | oracle | none |

Anchor enforcement (all five are checked and recorded in anchor-audit.json; a run with any check failing is INVALID):
E1 process: the anchor runs as a separate OS process (pid != harness pid), started by the runner before the harness.
E2 key: a 32-byte key from os.urandom inside the anchor process; it never crosses the socket until `close()`, which
   reveals it (written to `anchor/KEY.revealed`) after the run's last append. Receipts carry HMAC-SHA256(key, entry).
E3 filesystem: the harness+variant process runs under macOS `sandbox-exec` with a profile denying `file-write*` on the
   anchor directory; the anchor process (started outside the sandbox) holds the only writable fd. Fallback if
   sandbox-exec is unavailable: anchor dir 0555 / log 0444 after the anchor opens its O_APPEND fd, recorded as
   enforcement level "chmod" (author decision 2026-10-07 #2a: sandbox-exec + HMAC chain is the required level).
E4 known-negative probe: from inside the harness process, an attempt to open the anchor log for write, create a file in
   the anchor dir and chmod it each fail with PermissionError; recorded.
E5 log integrity: after close, the evaluator verifies the anchor log (hash chain + per-entry HMAC with the revealed
   key) and that its final head equals the head the anchor reported over the socket at close.
Variants receive only an AnchorClient (append/get/head over a Unix socket); they never receive the anchor path. The
import scan forbids paladin/conventional from importing r3_shared.anchor_server. No credit for obscurity: E3/E5 are the
enforcement, the hidden path is not.

## 5. What the attacker controls (tamper interface, neutral)

The attacker acts after a history is written and before replay, ONLY through `r3_shared.histstore.TamperView` on the
stream's HistoryStore: list keys, read bytes, put bytes (any key), delete key, rename key. It never touches the world
store, the anchor, the clock, tokens or variant code. The harness composes these primitives into the frozen mutation
classes (ORACLE-AND-HARNESS-G2.md section B3): mutate-field, delete-artifact, delete-envelope, substitute-artifact
(another real artifact of the same kind), rebind (point a decision at a later semantically similar artifact and
recompute its digest, envelope root and every later prev link), reorder (swap two envelopes and relink), truncate tail,
forge-receipt (rewrite stored receipts to match a rewritten chain), and compound (2-4 of these on one history).

## 6. Replay, explanation and continuation obligations

`Deployment.replay(decision_id)` (protocol section P1d-5) runs on a FRESH deployment of the same variant, deployed on
the SAME world store and HistoryStore with a NEW empty state_dir, the CURRENT authority/ops specs and an AnchorClient.
It returns VERIFIED only if ALL of: the envelope for decision_id exists; its root equals the anchor's entry for
(stream, seq) AND that anchor entry names the same decision_id; every prev link back to seq 1 matches the anchor's
roots; every bound artifact is present and its bytes hash to the bound digest; and re-evaluating the AUTHORITY
decision (PROT-H23 rule / PROT-H24 section 3 over the bound authority artifact, subject, on_behalf_of, operation and the
bound evidence refs) yields the recorded allow/deny. Business rules are not re-evaluated (their evidence set is not
fully bound, see Q6). It returns the envelope and artifacts it verified.
Otherwise TAMPERED (positive mismatch) or UNRESOLVED (something missing: artifact, envelope, anchor entry).

| Id | Requirement |
|---|---|
| R27-1 detection | Every frozen mutation class that changes any bound byte, binding, order or presence makes replay of each affected decision return TAMPERED or UNRESOLVED, never VERIFIED. |
| R27-2 no fallback-to-current | A missing historical authority/policy/contract/evidence artifact yields UNRESOLVED `missing_artifact`; replay never substitutes the current spec or current world object, even when byte-identical content would pass. |
| R27-3 no rebinding | VERIFIED returns exactly the artifacts bound at decision time (digest-equal to the oracle's expected binding); a later artifact never satisfies an earlier binding. |
| R27-4 clean histories | An untampered history replays every decision as VERIFIED with artifacts digest-equal to the oracle's expected binding (no false alarms). |
| R27-5 continuation | After tampering, a mutating request whose outcome depends on tampered history (stored approval, idempotency record of a committed request_id) either returns non-OK with zero effects or behaves exactly as on the untampered history (oracle effect check). A deleted idempotency record never yields a second effect. |
| R27-6 anchor before ack | No decision result is returned before its root is anchored (checked: every OK in the world log has an anchor entry). |
| R27-7 explanation | `explain(decision_id)` equals replay's verified envelope or carries the same TAMPERED/UNRESOLVED status (no prose fallback). |

## 7. Mutants (frozen in r3_shared.mutants.KNOWN["H27"])

- `digest_omission`: the policy digest is left out of the hashed envelope (stored beside it, not covered by root).
- `fallback_to_current`: replay uses the current authority/policy/contract when the historical artifact is missing.
- `evidence_rebinding`: replay resolves evidence by ref (latest stored version) instead of by bound digest.
- `receipt_self_trust`: replay checks the receipt copy stored in the HistoryStore instead
  of querying the anchor service.
Each must be killed by the corpus (>= 1 tamper case accepted as VERIFIED or a continuation effect), not by a unit test.

# H27 protections - Paladin variant (protection spec: spec/protections/PROT-H27.md)

Lines refer to the commit tagged `r3-g2-paladin`. Shape: the per-DECISION envelope is composed by the control plane
(`prov.py`) - not by an adapter, and distinct from the Engine's per-effect ProvenanceEnvelope (engine/provenance.py, v1.2, which
is unchanged and still written into the external system). Artifacts are content-addressed in the HistoryStore; the chain root of
every decision is appended to the anchor service before the result leaves the core.

## Requirements R27-1 .. R27-7

| Id | Where it lives | Mechanism |
|---|---|---|
| R27-1 detection | src/paladin/replay.py:50-100 (`replay`), :87 (root vs anchor), :93 (prev chain back to seq 1), :67 (envelope stored away from its own position), :135-141 (artifact digest) | Replay returns VERIFIED only if the stored envelope bytes hash to the ANCHOR's root for (stream, seq) naming the same decision id, every prev link back to seq 1 equals the anchor's root, every bound artifact is present and hashes to its bound digest, and the recorded authority verdict re-evaluates; a positive mismatch is TAMPERED, anything missing UNRESOLVED. |
| R27-2 no fallback | src/paladin/replay.py:133-135 | A missing historical authority/policy/contract/evidence artifact is UNRESOLVED `missing_artifact`; the current spec is never read on this path (only the `fallback_to_current` mutant calls `dep.current_artifact`). |
| R27-3 no rebinding | src/paladin/replay.py:120-141, src/paladin/prov.py:58-90 | Artifacts are resolved ONLY by the digest bound in the anchored envelope; VERIFIED returns exactly the bound bytes (`artifacts` digest -> bytes). A later artifact under the old digest fails the digest check. |
| R27-4 clean histories | src/paladin/prov.py:58 (`record`), src/paladin/evid.py (frozen artifact kinds), src/paladin/replay.py:146 (`_reauthorize`) | Envelope scalars/artifacts follow PROT-H27 s1-s3 exactly; replay re-evaluates the authority verdict from the BOUND authority artifact with the vendored Engine gate (src/paladin/authreplay.py) so honest histories replay VERIFIED. |
| R27-5 continuation | src/paladin/core_g2.py:228 (`guard_history`), src/paladin/core.py:204, :321 (`_approval_check`), src/paladin/prov.py:92-110 | A request id the anchor knows as an OK decision whose idempotency record is missing returns UNAVAILABLE `idempotency_record_missing` (never a second effect); a stored approval counts only if its decision is anchored with a provable envelope naming the same approver/operation/args AND the anchor's `<stream>.consumed` stream does not list it (spent approvals are recorded there, so a restored record is useless). |
| R27-6 anchor before ack | src/paladin/core.py:216-243 (`run` -> `_anchor`), src/paladin/prov.py:84-85 (`append` then receipt) | `finish` appends the root and stores the receipt before any result is returned; a failed append returns UNAVAILABLE `anchor_unavailable` (the committed effect is recorded as spent, replay says UNRESOLVED); a crash between world commit and anchor leaves the id `unanchored_after_crash` on retry (src/paladin/core.py:247), never an unanchored OK. |
| R27-7 explanation | src/paladin/deployment.py:301 (`explain`) | `explain` IS `replay` (one code path): same envelope when VERIFIED, same TAMPERED/UNRESOLVED otherwise, no prose fallback. |

## HISTORY_LAYOUT (declared completely; src/paladin/deployment.py:33, src/paladin/prov.py:19)
envelope `env/`, artifact `art/`, receipt `rcpt/`, evidence-by-ref index `ref/`, envelope sidecar `side/`, stream `meta/stream`,
approvals `led/appr/`, idempotency `led/req/`, ledger meta (attempts, authority in force, `used:<rid>` authority_used records)
`led/meta/`, authority versions `auth/`. In history mode there is no state_dir and no private sqlite file
(src/paladin/core.py:88; test_history_layout_declares_every_key_and_no_private_state).

## Mutants (constructor-activated, frozen names)

| Mutant | Site | Effect |
|---|---|---|
| digest_omission | src/paladin/prov.py:73 (policy digest taken out of the hashed envelope, kept in `side/<seq>`), src/paladin/replay.py:95 (replay reads it from the sidecar) | policy substitution passes: the digest is not under the anchored root |
| fallback_to_current | src/paladin/replay.py:133 | a missing bound artifact is replaced by the current spec's bytes and the replay is VERIFIED |
| evidence_rebinding | src/paladin/replay.py:126 | evidence resolved by ref (latest stored version in `ref/`), not by the bound digest |
| receipt_self_trust | src/paladin/replay.py:72 | the receipt copy in the HistoryStore replaces the anchor query, so a rewritten chain + rewritten receipts verifies |

## Assumptions about the (not yet written) oracle - recorded so a divergence is findable
- `effect_digest` = sha256(canonical_bytes(list of ALL world_log rows of the decision's transaction, WorldReader.log() row form,
  seq order, including the `commit` mark row)); `[]` for refusals. `world_seq` = seq of the `commit` mark row (effects, delegate,
  revoke) or the world_log head read when deciding (refusals, approve, already-revoked revoke). `tick` = `tx.tick`, or the clock for refusals.
- Reason codes: `ok`, `authority`, `delegation`, `no_valid_path`, `approval`, `policy`, `gate_pass`, `preconditions`, `constraints`,
  and the PROT-H24 s2/s5 reason for delegate/revoke refusals. Governed refusals are recorded; schema INVALID, unknown tool, bad token,
  UNAVAILABLE/UNKNOWN are not. `approve` has no request id in the Deployment protocol: its decision id is `approve:<stream seq>`.
- `newest` evidence tie-break: greatest field value, then smallest key. `operation` of delegate/revoke decisions = "delegate"/"revoke".
- Evidence refs are `<world type>:<key>`; the replay re-evaluation uses only refs whose type is a resource-input type of the operation.
- Replay verifies the whole prev chain back to seq 1 against the anchor (PROT-H27 s6 text), so tampering with an earlier envelope
  makes later decisions TAMPERED/UNRESOLVED as well.

## Known limits
- The authority document in force (`led/meta/auth_spec`) and `used:<rid>` records live in the attackable HistoryStore and are not
  anchor-checked on load; R27-5 protects the two continuation records the spec names (idempotency, approvals).
- Business rules are not replayed (Q6 scope limit).

# Gate 2 open questions - rulings needed before freezing PROT-H24 / PROT-H27 / P1d

Each with a recommended answer. "Author" = needs the author; "orch" = orchestrator may rule.

Q1 (author) Anchor filesystem enforcement level. The variants run IN the harness process, same OS user; no root.
  Options: (a) macOS sandbox-exec profile denying file-write* on the anchor dir for the harness process, anchor started
  outside the sandbox; (b) chmod 0555/0444 + held O_APPEND fd (same uid can chmod back); (c) a second OS user (needs sudo).
  RECOMMEND (a) as required, with (b) as defense in depth and E5 (MAC chain, key revealed at close) as the cryptographic
  check; if sandbox-exec fails on this macOS, rule (b)+E5 acceptable and record "enforcement=chmod" in anchor-audit.
  PROBE (designer, 2026-10-07, this host, scratch dir only): under `sandbox-exec -p '(version 1)(allow default)(deny
  file-write* (subpath D))'` a write into D and a chmod of D both failed "Operation not permitted" (rc 1) while a write
  outside D succeeded (rc 0). So (a) is feasible; P1d-8 must re-prove it as a test (known-negative + known-positive).
  Stdlib has no Ed25519; HMAC + delayed key disclosure avoids a new dependency. Alternative: add `cryptography` (shared
  low-level lib, allowed) for public-key receipts. Recommend HMAC (no dependency, same strength for this threat model).

Q2 (author) Safe-progress and race-realism thresholds for H24. thresholds.json has no H24 progress floor; the contract
  says measure progress separately and calls a harness that prevents races INCONCLUSIVE. RECOMMEND frozen in PROT-H24:
  unaffected-legit progress must be 1.0 (as H23 R8) else INCONCLUSIVE; >= 50% of concurrent cases overlap in real time
  and >= 1 effect-first order among overlapping RV cases, else INCONCLUSIVE. Numbers are design choices, not thresholds.json
  edits, and must be frozen before any run.

Q3 (orch) H24 reject mapping. reject_if names only stale effects and amplification; falsifiers 3-4 add races and cycles.
  RECOMMEND reject on any preregistered falsifier: cycle_grant > 0 and any linearizability_violation REJECT.

Q4 (orch) 4th H24 mutant `expiry_inclusive`. The contract lists three; expiry boundary exactness is otherwise only
  covered by the corpus. RECOMMEND add it (stronger proof; kill rate still required 1.0).

Q5 (orch) 4th H27 mutant `receipt_self_trust` (trust the stored receipt, not the anchor). It is the direct test of the
  trust split. RECOMMEND add it.

Q6 (author) Evidence set breadth. Binding objects found by `unique`/`exists` queries (e.g. InventoryLot for transfer)
  needs a frozen read-set for the expression language and enables full business-rule replay; costlier and a new
  oracle/variant disagreement surface. RECOMMEND the narrow set (resource inputs + `newest` terms) for H27 and record
  "business rules not replayed" as a scope limit in the H27 SUMMARY; widen in a later version if needed.

Q7 (author) Counting "5,000 histories". Generating 5,000 independent base histories per variant is slow; the plan uses
  >= 600 base histories each copied into many tamper cases (>= 5,000 tampered cases + >= 1,000 clean controls).
  The contract text says "histories/mutations". RECOMMEND count tampered cases, require >= 600 distinct base histories,
  both domains, and state the counting rule in the H27 SUMMARY.

Q8 (orch) False alarms. Falsifier 4 says material false positives falsify; reject_if omits it. RECOMMEND
  false_alarm > 0 -> REJECTED (preregistered falsifier), so a paranoid always-TAMPERED variant cannot be INCONCLUSIVE-safe.

Q9 (orch) Variant migration for H27: approvals and idempotency records move into HistoryStore when `history` is
  given. This touches H23-proven code paths in both variants. RECOMMEND both builders migrate behind the `history`
  parameter only (H23 path unchanged when history is None) and the full H23 suite + one H23 dev run re-pass before G2.

Q10 (orch) H24 interplay with H23 static delegates. Spec keeps them disjoint (static delegates can neither issue nor
  receive edges). RECOMMEND keep disjoint for Gate 2; H25 (constitutional authority) may unify them.

Q11 (orch) world_log is a protocol change to the world store under H23 evidence. RECOMMEND additive only (new table,
  H23 meter ignores it), full suite + H23 dev rerun as regression, H23 official verdicts untouched.

Q12 (author) Gate-2 stop rule wording. If one variant fails H24/H27 and the other passes, record per DUAL_TRACK (two
  verdicts, parity/difference descriptive), do not stop downstream gates unless BOTH reject (the conventional path stays
  the product path). RECOMMEND confirm.

## Rulings (2026-10-07)
Author: Q1 = (a) sandbox-exec + HMAC chain with key revealed at close; Q2 = floors as recommended (frozen in PROT-H24 s8);
Q6/Q7 = as recommended (narrow evidence set; count >= 5,000 tampered cases from >= 600 distinct base histories in both
domains + >= 1,000 clean controls; business rules not replayed is a recorded scope limit); Q12 = record two verdicts and
continue; stop downstream gates only if BOTH variants reject.
Orchestrator: Q3 yes (any preregistered H24 falsifier -> REJECTED incl. cycle_grant and linearizability violations);
Q4 yes; Q5 yes; Q8 yes (false_alarm > 0 -> REJECTED); Q9 yes (behind `history`, H23 suite + one H23 dev rerun as
regression); Q10 yes (static delegates and edges disjoint); Q11 yes (world_log additive; H23 official verdicts untouched).

## Errata (2026-10-07, after P1d, before any Gate 2 builder)
E-1 PROT-H24 s4 writes `tx.mark("authority", <kind>, payload)`; PROTOCOL-P1d P1d-1 defines `tx.mark(kind, payload)` and its
    mark list puts `op: delegate|revoke|set_authority` in the payload. The P1d form is binding:
    `tx.mark("authority", {"op": <delegate|revoke|set_authority>, ...})`. No semantic change.
E-2 validate_strict (P1d-3) does not check the root-edge delegable-grant rule or `redelegable` statically; both remain
    runtime issuance rules exactly as PROT-H24 s2 (steps 4-5). No semantic change.
E-3 (2026-10-07, after the G2 variant builds, before any H24/H27 measurement) delegate/revoke/authority_used while a v1
    authority spec is in force: treat it exactly as a v2 document with `capabilities: []`, `revoked: []` and
    `max_delegation_depth: 8` (PROT-H24 s1 frozen maximum). Never an uncaught exception (every call returns a CallResult).
E-4 (2026-10-07, after the G2 builds, before any H27 measurement) Envelope encoding details PROT-H27 s1-s2 left open.
    The oracle's forms (r3_oracle/provenance.py at r3-g2-h27-harness) are binding for both variants:
    - `operation`: the operation name for call_tool/direct/approve; null for delegate/revoke.
    - `args_digest` = sha256(canonical_bytes(X)) with X = the args dict exactly as passed for call_tool/direct; for approve
      the approved request's `args` dict (not a wrapper); the edge dict for delegate; the edge_id STRING for revoke.
    - `decision_id`: the request_id for call_tool/direct/delegate/revoke; for approve a variant-chosen id unique within
      the stream (the oracle reads it from the envelope).
    - `effect_digest` = sha256(canonical_bytes([row...])) over ALL world_log rows of the decision's transaction (marks
      included), seq order, each row with all columns; [] for refusals.
    - `world_seq`/`tick`: the transaction's `commit` mark seq/tick; else the last effect row; else the world_log head and
      clock read when deciding.
    - `newest` evidence tie-break: greatest field value, then the smallest ref.
    - policy artifact = canonical {"config", "business_rules", "approval"}; contract artifact = canonical(op minus
      business_rules/approval, plus "helpers" and "spec") - exactly PROT-H27 s1.
E-5 (2026-10-07, after H24 dev run 1 - dev runs are not measurements; no official G2 run exists) `set_authority` replaces
    the BASE layer only (principals, grants, static delegations, max_delegation_depth). Any `capabilities`/`revoked` in a
    set_authority document are ignored: edges and revocations change only through delegate/revoke (commit-ordered, marked).
    There is no un-revoke by any path (PROT-H24 s5). authority_version() still hashes the full v2 document in force.
E-6 Every SUPPORTED-type resource reference supplied in a request - required or optional - must resolve to an existing
    object of its declared type at commit, otherwise INVALID with zero effects (PROT-H23 R6 "target existence"; extends
    ruling R-2 from optional to required refs). Oracle and variants identically.
E-7 `Variant.deploy` never raises because of HistoryStore content. A tampered/unreadable history (including the authority
    version record) must surface through replay/explain as TAMPERED or UNRESOLVED and, for mutating calls that depend on
    it, as a non-OK result with zero effects (R27-5). The harness wraps deploy; a remaining deploy exception is recorded as
    `deploy_crash` (not a tamper acceptance; blocks SUPPORTED -> INCONCLUSIVE).
E-8 Governed decisions (PROT-H27 s1): the ORACLE decides from the ops-spec input schema whether a request is
    schema-INVALID (no envelope); every other result with status OK, DENIED or INVALID is governed and must have exactly one
    envelope at its stream position. Variants must envelope exactly that set, independent of their reason strings.
E-9 (2026-10-07, after G2 fix round 1, before any official G2 run) The schema-INVALID set of E-8, exactly:
    - call_tool/direct/approve: the operation is unknown, OR args is not an object, OR args has a key that is not a
      declared input (unknown keys are schema-INVALID - consistent with PROT-H23 R1), OR a required input is missing or
      null, OR a supplied input fails its type (integer: int not bool; number: int or float not bool; boolean: bool;
      string: str; resource: non-blank str; json: any value). Existence of a referenced object is NOT schema (E-6: it is
      a governed INVALID). For approve the same check applies to the approved request's operation and args.
    - delegate: the edge fails the authority-spec-v2 edge schema (PROT-H24 s1 / schemas/authority-spec-v2.schema.json).
      Semantic issuance refusals (cycle, unknown parent, amplification, ...) are governed.
    - revoke: edge_id is not a non-empty string. unknown_edge / not_revoker are governed.
    The oracle function r3_harness/h27/stream.py:oracle_schema_invalid implements exactly this; each variant envelopes
    exactly the complement; a shared conformance test compares them on generated edge cases.

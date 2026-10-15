# Gate 2 oracle, harness and evaluator design (H24 + H27)

DRAFT g2-design (2026-10-07). Packages: r3_oracle (imports r3_shared only), r3_harness/h24, r3_harness/h27 (variants only
via the registry). Same corpus and evaluator for both variants; two verdicts + comparative record per gate.

## A. H24

### A1 Oracle: r3_oracle/authority_v2.py (immutable reference DAG)
- Pure functions over frozen facts: `RefAuthority.from_spec(v2_spec)` -> immutable value; `apply(event)` returns a NEW
  value (delegate/revoke/set_authority events, each with its own issuance verdict per PROT-H24 s2); `decide(subject, obo,
  op, resources, tick)` per PROT-H24 s3 returning (allow, reason, valid_paths). Scope helpers re-implemented here
  (not imported from authspec); a parity test compares them with r3_shared.authspec helpers on generated scopes.
- Inputs it consumes: the harness's own schedule record (what was requested, by whom, invoke/return order) and the world
  store's world_log (commit order, tx.tick, marks, writes). It never reads CallResult except to label refusals, and never
  calls a variant. Clock values come only from world_log tick stamps and the harness schedule (frozen clock model).
- Judging a run: walk world_log in seq order. On an `authority` mark, compute the oracle's issuance verdict for the
  matching harness request: mark present for a request the oracle refuses -> `edge_accepted_illegitimately`
  (scope_amplification when the reason is scope/expiry amplification, cycle_grant when cycle/static/unknown parent).
  Missing mark for a request the oracle accepts and the variant answered OK -> `authority_ack_without_commit`.
  On a `commit` mark: oracle.decide at that seq/tick; not allowed -> `post_boundary_effect` when some path was valid at an
  earlier seq or tick (stale), else `forbidden_effect`; the effect itself is checked with the H23 ops model.
  Then linearizability: for every pair with harness happens-before X->Y, seq(X) < seq(Y), else `linearizability_violation`.
  Refused requests: legal in EVERY linearization consistent with real time -> `progress_loss`; legal in some -> `race_refusal_ok`.
- `authority_used(request_id)`: returned path must be in oracle.valid_paths at that seq and the version must equal the
  oracle's version digest at that seq, else `historical_mismatch`. After the path is revoked, the harness re-sends the
  request with a new request_id: allowed -> post_boundary_effect.

### A2 Generators (r3_harness/h24/gen_*.py, seeded RNG, schema-validated inputs)
- Authority DAG generator: 6-14 fresh principals (delegated_by null) + the domain fixture's principals; root edges from
  principals holding delegable grants (a neutral-extension grant set generated per sequence, validated by validate_strict);
  chains depth 1..8 with >= 25% depth >= 4; fan-out up to 3 (DAG at principal level: a principal reachable by several
  paths from one or several roots); scopes drawn as subsets (legal) or with one injected widening (illegal: extra op,
  extra key, keys null where parent has keys, later expiry); cycle attempts (child = an ancestor issuer); static-delegate
  mixing; depth overflow; duplicate ids.
- Sequential state machine (hypothesis.stateful-style, executed with seeded RNG): steps delegate | revoke | advance(n) |
  set_authority(narrowed base) | request(subject, obo, op, args) | retry(request_id) | crash/restart | authority_used.
  One SEQUENCE = one generated graph + 20-60 steps. Target 10,000 unique sequences per variant (thresholds
  min_authority_sequences), both domains, every operation.
- Race generator (>= 1,000 CONCURRENT cases per variant, thresholds min_concurrent_revocation_cases), types cycled:
  RV  revoke(edge on the path, any depth) || request via that path      (barrier start, two threads)
  RA  revoke(ancestor edge, depth >= 4 path) || request by the leaf holder
  EX  advance(clock to expires_at) || request via the expiring path
  SA  set_authority(remove root grant) || request
  DP  delegate(child of e) || revoke(e)
  AP  revoke || consume a pre-approval on a delegated request
  CR  revoke armed with after_commit/before_commit crash || request; restart; replay same request_id; new request_id
  UN  revoke in subtree A || 2-4 legitimate requests in unrelated subtree B (progress probe)
  SEQ the same pairs strictly sequenced both ways (happens-before known) - control for the winner rule
  Each case records invoke/return order from a harness-side counter (not wall clock), world_log slice, and overlap flag.

### A3 Classifications (one row per call/case)
forbidden_effect, post_boundary_effect, scope_amplification, cycle_grant, linearizability_violation,
authority_ack_without_commit, unattributed_write, writer_violation, unlogged_write, historical_mismatch,
progress_loss, race_refusal_ok, explicit_reason_mismatch (measured, not a verdict clause), unsupported,
world_lock_timeout (unmeasurable, never safe), ok.

### A4 Evidence files (exact contract names) per variant directory
- authority-state-machine.json: sequences (gz jsonl sibling + sha256), per-class counts, depth histogram, op/domain coverage.
- revocation-races.json: every race case (type, overlap, order, oracle outcome, variant outcome, class).
- delegation-attenuation.json: every delegate attempt (legal/illegal by generator intent, oracle verdict, mark present).
- safe-progress.json: PROT-H24 s8 metrics (unaffected-legit progress, overlap fraction, order split, p50/p95 latency).
- mutation-results.json: per KNOWN["H24"] name: killed, killing class, first killing case id.
- envelope.json (r3_shared.evidence) hashing all of the above + PROT-H24.md sha256 + evaluator sha256.

### A5 Evaluator clauses (r3_harness/h24/evaluator.py) -> contract + thresholds.json H24
| Contract clause | Computed as (recomputed from raw rows) |
|---|---|
| support: 0 scope-amplifying delegations | scope_amplification == 0 (max_scope_amplifications) |
| support: 0 forbidden effects after effective revocation/expiry | post_boundary_effect + forbidden_effect + unattributed/writer/unlogged == 0 (max_post_revocation_forbidden_effects) |
| support: 100% races match the oracle | concurrent cases with variant outcome == oracle outcome AND no linearizability_violation / executed == 1.0 (required_oracle_equality), executed >= 1,000 |
| support: no cycle case silently grants | cycle_grant == 0 |
| support: 100% target mutations detected | killed / len(KNOWN["H24"]) == 1.0 |
| reject_if | scope_amplification > 0 OR post_boundary_effect/forbidden_effect > 0; PROPOSED also cycle_grant > 0 and linearizability_violation that let a stale commit through (falsifiers 3-4; Q3) |
| inconclusive_if: corpus lacks nesting/expiry/concurrent revocation | no sequence with depth >= 4 (min_delegation_depth); no EX case; overlapping concurrent cases < 1,000; sequences < 10,000; a race type or domain/op missing |
| inconclusive_if: races prevented by the harness | overlap fraction among concurrent cases < 0.5 OR zero effect-first orders among overlapping RV cases (PROPOSED numbers, Q2) |
| inconclusive (proposed, Q2) | unaffected-legit progress < 1.0; any `unsupported`; any world_lock_timeout |
| invalid_if: wall-clock reuse / semantics changed after races | oracle import scan (no variant, no `time`/`datetime` in r3_oracle/authority_v2.py); PROT-H24.md sha256 in envelope == frozen hash in protocol FREEZE amendment; envelope/evidence hash mismatch |
Precedence via r3_shared.verdict.evaluate_common (INVALID > REJECTED > INCONCLUSIVE > SUPPORTED); minimum overrides
stamped and refused on non-dev experiment ids (H23 P9 rule).

### A6 Known-negative fakes (tests/fakes, never registered)
FakeAmplifier (accepts any delegate, uses last scope), FakeStaleCache, FakeEarlyAck (revoke acks then applies after the
next commit), FakeInclusiveExpiry, FakeCycleGrant, FakeSerializer (refuses everything UNAVAILABLE during a revoke ->
must be INCONCLUSIVE, not SUPPORTED), FakeHonest (reference implementation over the oracle -> SUPPORTED on a small
corpus with dev overrides). Each fake must yield exactly its expected class set; the evaluator test asserts the verdict.

## B. H27

### B1 Oracle: r3_oracle/provenance.py (expected bindings, anchor-based)
- Before any tampering, the harness computes the EXPECTED BINDING of every decision independently: evidence artifacts
  reconstructed from world_log at the decision's seq (PROT-H27 s1 evidence set), authority digest = oracle's v1/v2
  version at that seq, policy/contract digests from the frozen ops spec files, decision scalars from the harness request
  record + world_log commit mark. Written to `expected-bindings.jsonl` and hashed into the envelope BEFORE tampering.
- Independent root check: for each decision, the oracle recomputes the envelope root from its expected binding and the
  chain, and compares with `verify_anchor_log` output (the anchor, not the HistoryStore). A clean history whose anchored
  root differs from the oracle's expected root = `binding_divergence` (the variant bound something else: INVALID-for-
  variant evidence -> counted as a false-alarm-class defect, see B5).
- Tamper verdict: for a tamper case, `affected` = decisions whose bound bytes, binding, order or presence the applied
  primitives changed (computed from TamperView.log against expected bindings). Expected replay for affected decisions:
  not VERIFIED; for unaffected decisions in the same history: VERIFIED with expected artifacts (else false alarm).

### B2 History generator (r3_harness/h27/gen_history.py)
Sequential, both domains, 5-30 decisions per history mixing OK/DENIED/INVALID-rule, approvals, H24 delegate/revoke,
set_authority between decisions (so historical authority != current), EvidenceSnapshot refresh (later similar
artifacts exist for rebinding), at least one committed request_id per history (continuation probe). Base histories:
>= 600 per variant (300 per domain); each base history's world + HistoryStore files are copied per tamper case.

### B3 Tamper corpus (frozen classes; composed only from TamperView primitives)
T1 mutate-field (one byte/field of an artifact, envelope or receipt); T2 delete-artifact (evidence/authority/policy/
contract); T3 delete-envelope; T4 substitute (same-kind artifact from another decision); T5 rebind (later similar
artifact + recomputed digest, root and all later prev links); T6 reorder (swap two envelopes, relink); T7 truncate tail;
T8 forge-receipt (T5/T6 plus rewritten stored receipts); T9 continuation (delete idempotency record / alter stored
approval, then send the request); C compound (2-4 of T1-T9 on one history, >= 20% of cases). Clean controls: >= 1,000
untampered copies replayed. Total tampered cases >= 5,000 per variant (min_provenance_histories; counting rule Q7).
Artifact location: the harness finds artifacts by CONTENT (oracle expected canonical bytes and frozen envelope form);
the variant's HISTORY_LAYOUT declaration is used only for records with no frozen form (approvals, idempotency).

### B4 Evidence files (exact contract names)
provenance-bundles.jsonl (every base decision: expected binding, anchored root, variant envelope);
tamper-mutation-results.json (case, primitives log, affected set, replay/explain status per decision, class);
historical-replay.json (clean controls: per decision VERIFIED + artifact equality); anchor-audit.json (E1-E5 + pid,
enforcement level, revealed-key MAC check, head match); mutation-results.json (KNOWN["H27"]); envelope.json.

### B5 Classifications and evaluator clauses -> contract + thresholds.json H27
Classes: tamper_accepted (affected decision VERIFIED), fallback_to_current (missing artifact case VERIFIED or
explained with current content), rebinding_accepted, continuation_effect (effect differs from untampered oracle),
false_alarm (clean or unaffected decision not VERIFIED or artifacts != expected), binding_divergence, unanchored_ack.
| Contract clause | Computed as |
|---|---|
| support: 100% tamper mutations detected | (affected decisions not VERIFIED) / affected == 1.0 (required_tamper_detection_rate), all T-classes present |
| support: 0 silent fallback-to-current | fallback_to_current == 0 (max_silent_fallback_to_current) |
| support: 100% untampered reconstruct, no false alarms | false_alarm + binding_divergence == 0 (max_false_tamper_alarms_on_clean_history) over >= 1,000 controls |
| support: 100% target mutations detected | kill rate 1.0 over KNOWN["H27"] |
| reject_if | tamper_accepted + rebinding_accepted + fallback_to_current + continuation_effect + unanchored_ack > 0 |
| inconclusive_if | anchor-audit E1 or E2 fails (no independent anchor); compound class absent; tampered cases < 5,000; any `unsupported` |
| invalid_if | anchor-audit E3/E4/E5 fails (anchor writable or rewritten); canonicalization changed after mutations (PROT-H27 s3 + canonical_bytes source sha256 in envelope != frozen); oracle imports a variant; evidence hash mismatch |

### B6 Known-negative fakes
FakeNoAnchor (self-signed roots in HistoryStore -> INCONCLUSIVE/REJECTED), FakeOmitDigest, FakeFallback, FakeRebind,
FakeReceiptTrust, FakeParanoid (always TAMPERED -> REJECTED-by-false-alarm path must NOT be SUPPORTED: false_alarm > 0
-> not support; verify it is INCONCLUSIVE or REJECTED per Q8), FakeAnchorWriter (the fake writes into the anchor dir ->
E4/E5 must fire -> INVALID). FakeHonest -> SUPPORTED on a small dev corpus.

# Protection specification H28 - Byzantine adapters are neither authorities nor truth oracles (both variants)

DRAFT (g4-design, 2026-10-09, repo HEAD d055679). Requirement-level; the ONE place the H28 rules are written;
r3_oracle/extoracle.py, both variants and r3_harness/h28 implement exactly this text. Attack class A7
(A7_BYZANTINE_ADAPTER). Contract: hypotheses/h28/contract.json. Protocol: PROTOCOL-P1f.md (P1f-1..P1f-9).
Upstream: H23 (decision plane, request_id idempotency, crash points), H27 (provenance envelope = byte-exact
`envelope_text` handed to the adapter). Author decision 2026-10-06 s4: the observer reads the external effect ledger
directly and never consumes the action adapter's response.

## 0. Current seam (as found at d055679) and why it cannot be measured as is

- Both variants write external effects with `WorldHandle.external_write` INSIDE the request's world transaction, into
  the `external_effects` table of the variant-written world file. The "adapter" is a string label; no credential exists.
- Paladin: `worldbridge.WorldExternalAdapter.apply` writes the effect AND fabricates its own observation
  (`observations()` -> `transferStatus: COMMITTED`, ERP `expectedAt - 1` hard-coded); `engine/outcome.py` feeds those
  adapter observations to the outcome predicate -> an adapter lie becomes RECONCILED_SUCCESS by construction.
- Conventional: `effects.apply` writes the effect inline; no adapter object, no observation, no outcome state.
- Project domain: no `external` effect exists in spec/ops/project.json (Paladin routes canonical writes through a
  `git_change` "adapter" that is in-process store code, not an external system).
Consequence: H28 needs a NEW seam (P1f) that both variants adopt; the legacy path stays for H23-H27 (s9).

## 1. Definitions (frozen)

1.1 External system: a harness-owned system `S` in the ExternalWorld service (P1f-2) with a frozen declaration
    (P1f-3): name, operations, target namespace, idempotency class per operation (s4), observability class (s5).
1.2 Action adapter: the object a variant calls to carry ONE intended external effect to S. Adapters are supplied by
    the harness through the deploy parameter `external` (P1f-1) - the SAME injection point for both variants. The
    variant may not wrap, subclass or replace them; it calls `adapter.submit(ExternalRequest)` only.
1.3 Variant adapter-side code (ADAPTER_MODULES): every variant module that builds an ExternalRequest, mints or stores
    an external capability, calls submit, interprets replies, retries, or reads the observer. Declared by each variant
    (P1f-8) and subject to the governance audit (s6.2).
1.4 Intended effect I(d) of a committed decision d (oracle-computed, never read from the variant): the tuple
    (system, operation, target, payload_digest, correlation = d.request_id) derived from the ops-spec `external`
    effect of d's operation applied to d's canonical inputs (P1f-3 payload rule). One per external effect of d.
1.5 External capability (cap): an attenuated bearer token (P1f-4, macaroon-style HMAC chain rooted in a key that only
    the ExternalWorld process holds). Caveats: system, operation, target, payload_digest, correlation, max_uses,
    not_after_tick. Attenuation can only narrow; ExternalWorld verifies every caveat on every write attempt.
1.6 Observer: the ObservationClient (P1f-5) - a read-only connection to the ExternalWorld ledger file with its own
    observation key; it is the ONLY outcome evidence a variant may use.

## 2. Decision plane: governance never depends on the adapter (R28-1, R28-2)

R28-1 Decide-before-dispatch. The governed decision (status, reason, authority_used, approvals consumed, canonical
      world effects, H27 envelope) of every request is final BEFORE any adapter is called, and is identical whatever
      any adapter later does. Check order unchanged from PROT-H23/G3-E17; dispatch comes after the world commit.
R28-2 No adapter-minted authority. Nothing in an adapter reply (any key, e.g. approval, grant, on_behalf_of, policy,
      status:"approved"/"denied") is read by authority, approval, delegation, governance or disclosure code. An adapter
      refusal (any reply, incl. a policy-sounding reason) is an OUTCOME fact (s3), never a DENIED decision, never a
      gate entry in the envelope, never a new approval/grant.
R28-3 Generic enforcement. Every deny rule, precondition, approval and authority check of the ops spec / auth spec is
      enforced in the decision plane. Moving any of them into adapter-side code (1.3) - even if the effect is then
      blocked - is `governance_in_adapter` (falsifier 3). Measured behaviourally first (s6.1), statically second (s6.2).

## 3. Outcome plane: adapter replies are hints, observer rows are truth (R28-4..R28-6)

R28-4 Outcome vocabulary (P1f-6, frozen, exact strings): PENDING, RECONCILED_SUCCESS, RECONCILED_FAILED, DIVERGED,
      UNKNOWN; plus confidence `full` | `low`. Every committed decision with >= 1 external effect has exactly one
      outcome record per external effect, keyed (request_id, effect_index).
R28-5 Outcome function. The state is the pure function `outcome_state` of P1f-6 over (I, the observer rows correlated
      to I's cap chain, the observer watermark, the cap expiry, the idempotency class, the observability class, the
      previous state). The adapter reply is NOT an argument. Variants implement it themselves (not shared code, ruling
      Q4 recommendation); r3_oracle implements it independently; conformance C28-2 compares them.
R28-6 Monotone safety. At every reconcile point the variant's state equals the oracle's state at that point (same
      observer snapshot - the harness passes the observer watermark, P1f-5). RECONCILED_SUCCESS is reported only with
      a corroborating observer row; a reported RECONCILED_SUCCESS the oracle does not give at that point is
      `false_reconciled_success` (falsifier 2) even if a later observation would have corroborated it.

## 4. Idempotency / replay semantics per action class (R28-7, R28-8) - makes "duplicate beyond semantics" decidable

Each external operation declares exactly one class (P1f-3, frozen per system):
- `at_most_once`: at most ONE applied effect matching I per (request_id, effect_index). Manufacturing WMS.transfer
  (ops-spec note "exactly one WMS command per authorized request") and ERP.expedite (fee charged per call).
- `idempotent_set`: any number of applied effects with payload_digest == I.payload_digest is harmless (state-setting
  write); any applied effect with a different payload is a mismatch (s3), not a duplicate. MES.reschedule.
- `exactly_once_required`: as at_most_once, and RECONCILED_FAILED is a progress loss for honest adapters (s8).
R28-7 duplicate_effect := number of applied ledger rows matching I beyond the class allowance (at_most_once: rows-1 when
      rows > 1; idempotent_set: 0). Counted per I from the LEDGER only. Falsifier 4 when > 0.
R28-8 Retry and redelivery. A variant may resubmit I (adapter TIMEOUT/FAILED reply, crash after commit then restart)
      only with the SAME cap (same chain id); it never mints a second cap for the same (request_id, effect_index).
      max_uses = 1 for at_most_once/exactly_once_required; for idempotent_set max_uses <= 3 (frozen). A replayed
      request_id (PROT-H23 R5) never dispatches again once the effect has an outcome record.

## 5. Observation independence and the stop rule (R28-9, R28-10)

R28-9 Observation path. The observer reads ExternalWorld's ledger file read-only (SQLite mode=ro) with an observation
      key distinct from every action cap root; it sees, for the systems of its scope: applied effect rows and the
      ExternalWorld AUDIT rows (every refused write attempt with its reason and cap chain id) - the analogue of a
      cloud audit log that records denied calls. It never sees adapter replies, variant logs, world_log or
      HistoryStore. Topology frozen in observation-independence.json (P1f-5); action and observation paths must share
      no key, no connection, no process-owned object (checked, s8 inconclusive clause).
R28-10 Observability classes (frozen per system, P1f-3):
      `full`  - effect rows + audit rows visible; normal outcome function.
      `effects_only` - effect rows visible, audit rows NOT visible (refused attempts invisible): target substitution
                that the cap refused is undetectable from this path; such systems are excluded from the 100% target-
                mutation denominator and reported separately (scope limit, stop rule).
      `none`  - no observation path. STOP RULE: the variant must report UNKNOWN with confidence `low` for every
                effect on such a system for ever; any other state = false closed-loop claim (counted as
                false_reconciled_success if RECONCILED_SUCCESS, else outcome_mismatch).
      Observer faults (harness-injected, A9-like): UNAVAILABLE (read raises) and LAGGING (watermark held back). Observer
      integrity is a trust root and is NOT attacked (scope limit: compromise of every independent root is out of
      scope, threat_model).

## 6. Governance-in-adapter detection (R28-11, R28-12) - behaviour first, static second

R28-11 Behavioural (primary). (a) Twin differential: every Byzantine case is also run on an honest twin deployment
      (same seed, world, requests, schedule); the decision plane (status, reason, authority_used, canonical world
      diff, envelope digests excluding outcome records) must be byte-identical (canonical JSON). Any difference =
      `adapter_influenced_decision` (counts as governance_in_adapter). (b) Oracle decision equality: for every
      request the variant status equals r3_oracle ops_model.evaluate (H23 oracle). A request the oracle DENIES that
      the variant answers OK (effect possibly blocked later by adapter-side code) = governance_in_adapter.
      (c) Policy-reply probes: adapters G1-G3 (catalogue) return policy-shaped replies / authority artefacts; any
      later decision that consumes them (approval satisfied, path containing adapter-supplied ids) = governance_in_adapter.
R28-12 Static closure audit (secondary, frozen review): each variant declares ADAPTER_MODULES (P1f-8). An AST scan of
      their import closure flags (i) any import of the variant's authority/policy/approval/governance/disclosure
      modules, (ii) any Compare/If/dict-dispatch reading reply keys in R28-2's list or authority vocabulary (grant,
      principal, role, approval, policy, on_behalf_of, threshold), (iii) any ops-spec business-rule literal (deny-rule
      or precondition `when` constants). Hits are reviewed BEFORE the official run into the frozen file
      spec/gate4/ADAPTER-AUDIT-RESOLUTIONS.json keyed (variant, file, normalised hit line) with the G3-E24/E29
      resolvability rules restated for adapters: resolvable only if the code touches a FROZEN PROTOCOL field of P1f
      (cap caveat names, outcome vocabulary, reply-status vocabulary of P1f-1) and never decides a request's
      governed status. Unresolved hit = governance_in_adapter. Self-test: the `policy_gate_in_adapter` mutant build
      must be flagged by BOTH (behavioural and static); the oracle and FakeHonest must report 0.

## 7. Credential and resource scoping (R28-13, R28-14)

R28-13 Per-effect attenuation. For each I the variant attenuates its root cap for S (issued by ExternalWorld at deploy,
      P1f-4) to exactly: system=S, operation=I.op, target=I.target, payload_digest=I.payload_digest,
      correlation=request_id#effect_index, max_uses per s4, not_after_tick = commit_tick + WINDOW (frozen, P1f-3).
      The adapter receives only that cap. The root cap never leaves adapter-side code (never in an ExternalRequest).
R28-14 effect_outside_scope := an APPLIED ledger row (any system) whose (system, op, target, payload_digest,
      correlation) equals no I(d) of any decision the ORACLE says committed. Measured from the ledger + oracle
      decisions only, never from caps, adapter replies or variant claims. Falsifier 1 when > 0. (A broad cap only
      matters when a Byzantine adapter uses it - which the corpus guarantees for every scope-attack case.)

## 8. Classifications, safe progress and floors (evaluated per variant, same corpus)

Violation classes (falsifiers; any > 0 -> REJECTED): effect_outside_scope (R28-14), false_reconciled_success (R28-6,
R28-10 none-class), governance_in_adapter (R28-3, R28-11, R28-12), duplicate_effect (R28-7).
Detection clause: target_mutation_detected = 1.0 - over every case whose adapter made >= 1 write attempt with
(op, target, payload) != I carrying I's cap on a `full` system, the variant's final state for that I is DIVERGED.
Not 1.0 -> REJECTED (recommended mapping, Q6); fewer than 300 attempted -> INCONCLUSIVE.
Non-falsifier mismatch classes (block SUPPORTED, verdict INCONCLUSIVE - anti-masquerade floors, same pattern as
PROT-H24 s8 / H25 s7 / H26 s9):
- outcome_mismatch: final or intermediate state != oracle state, other than a false RECONCILED_SUCCESS (e.g. a
  variant that answers UNKNOWN for everything). Floor: outcome equality 1.0 over all reconcile points.
- progress_loss: honest twin, oracle OK, `full` system, honest adapter -> final state must be RECONCILED_SUCCESS.
  Floor 1.0 (a deny-everything or never-dispatch variant cannot pass).
Floors (frozen here, not in thresholds.json): >= 5,000 Byzantine cases (thresholds H28.min_byzantine_adapter_cases),
>= 1,000 honest positive controls with observable effects in BOTH domains (contract inconclusive_if), >= 300 cases per
catalogue primitive (P1f-7 list) and >= 300 per (domain, system), >= 200 crash-after-commit redelivery cases,
>= 300 `none`-class cases, >= 300 observer-fault cases. Unmet floor -> INCONCLUSIVE.

## 9. Mutants (P1f-9) - each must be killed by its OWN class on the frozen corpus

Contract-required (python_hypothesis_role.mutation_proof + step 6):
- adapter_success_trusted   - outcome taken from adapter reply OK -> RECONCILED_SUCCESS. Killed by false_reconciled_success.
- credential_scope_broadened - adapter receives a cap without target+payload caveats (system+op only). Killed by
                               effect_outside_scope (target-substitution adapters).
- policy_gate_in_adapter    - the manufacturing approval rule `expedite-large-fee-needs-approval` (and, if the Q2
                              overlay is accepted, its project analogue) removed from the decision plane and enforced
                              in adapter-side code before submit (the request commits OK without approval; the
                              adapter-side code then refuses to dispatch). Killed by governance_in_adapter (R28-11b and R28-12).
- idempotency_disabled      - every (re)submission mints a fresh cap (max_uses unbounded). Killed by duplicate_effect.
- observation_coupled       - reconciliation consumes adapter-reported observations (Paladin today) instead of the
                              observer. Killed by false_reconciled_success on lying adapters.
Justified extra:
- divergence_rewritten      - any correlated applied row counts as success (target/payload not compared). Killed by
                              target_mutation_detected < 1.0 / outcome_mismatch; proves the detection clause non-vacuous.
Kill rule: a mutant is killed only if its own class is > 0 AND the non-mutated build is 0 on that class (G3 lesson:
N must equal the inheriting population; report the exact failing case ids).

## 10. Scope limits declared up front (recorded in every SUMMARY)

L1 Observer integrity is trusted (only availability/lag faults). L2 `effects_only`/`none` systems: refused attempts /
all effects are invisible; outcomes there are lower-confidence by declaration (stop rule), excluded from the detection
denominator, reported separately. L3 Adapter attack code = the frozen catalogue (P1f-7) and its generated compositions;
adapters run in the harness process but never receive a root cap or a variant object (they get ExternalRequest only).
L4 Wall-clock delay is modelled in logical ticks. L5 Payload equality is byte-exact canonical JSON digest (no semantic
equivalence). L6 Project-domain external effects exist only through the H28 ops overlay (Q2) - if the author rejects
the overlay, H28 covers manufacturing + generated systems only and says so. L7 Legacy in-transaction `external_write`
remains the H23-H27 path; H28 verdicts say nothing about it.

## 11. Regression

Both variants re-pass the H23/H24/H25/H26/H27 suites and one H23 dev run with `external=None` (legacy path) before any
H28 dev run (G3 ruling Q9 pattern). Official verdicts of earlier gates are untouched.

# H30 step 0 - can BR(task, Paladin) and BR(task, conventional) differ? Static analysis of round3 HEAD

Scope: round3 HEAD (d02cbcd), src/paladin, src/conventional, src/r3_shared, spec/protections/PROT-H30.md s1-s4,
spec/gate6/EQUIVALENCE-G6.md, threat_model/attack_classes.json. Read-only; nothing was run. Out-of-bounds files were not opened.
G6 seams on r3-harness / r3-paladin / r3-conv are noted only in s6.

Deploy-mode assumption (important, see D1 in s4): L2 ("publish the narrowed authority document") only exists when the variant
is deployed with `authority_source` (G5 path; the harness never calls set_authority, r3_shared/variant.py:229-232), and R2/R3 use
the G5 host plus H27 replay, so the analysis assumes the G5 + history + anchor + external deployment (Paladin `_h29 = True`,
paladin/continuity.py:36). At HEAD no H30 runner exists (src/r3_harness/h30 has overlay_gen/rules/validate only), so this mode is
NOT frozen anywhere yet *(fact)*. Cells whose verdict depends on it are flagged.

Common facts used by many cells *(fact)*:
- F1 Identity: one TokenVerifier is built by the host (r3_shared/host.py:116, `IdentityProvider(secret).verifier()` -> revocation
  list from R3_REVOCATION_PATH, r3_shared/identity.py:150-178) and passed to both variants. Paladin checks it on every entry
  (paladin/core.py:176-186, called from deployment.py:195, 236, 261, 318, 356, 381); conventional on every entry
  (conventional/service.py:238-242, called from service.py:333, 532, lowreads.py:24, lowevents.py:31/55, authority_ops.py:108).
  Neither caches a verified token. So L1 stops every NEW call by K the next tick in both: SHARED.
- F2 Neither variant at HEAD consults identity revocation for anything K created earlier: stored approvals, delegation edges,
  outbox intents. These are stopped only by L2 (authority narrowing re-checked at commit), L3 (edge revoke), L4 (chain revoke,
  server side) or nothing.
- F3 Authority version: both fetch the lease on every governed call and adopt it before deciding (paladin/continuity.py:74-89 ->
  _adopt 57-72 -> core_g2.py:76-89 replace_authority(keep_edges=True); conventional/g5svc.py:101-142 -> authority_ops.py:51-62
  _compose_base). Both keep runtime edges and revocations across a publish. L2 takes effect at the next governed call in both.
- F4 Edge-path validity: same rule in both (PROT-H24 s3 a-f): revoked/expired edges, scope on every edge, base authority of the
  ROOT only, deny grants of subject/issuers (paladin/capgraph.py:202-215 + core.py:405-407 pre_authority of Q; conventional/pdp.py:41-57).
  Neither checks that an intermediate issuer still holds ALLOW grants, so narrowing K's grants does not invalidate edges K issued
  under a parent edge (Q->K->X); it does invalidate edges rooted at K (rule e). Equal in both.
- F5 External effects: per-effect cap with the same caveat set and the same max_uses (paladin/extdispatch.py:33-42,19;
  conventional/extout.py:56-62,77; at_most_once/exactly_once 1, idempotent_set 3) and no re-authorization at dispatch in either
  (paladin/extdispatch.py:73-111; conventional/extout.py:121-152). Every write is decided by the shared ExternalWorldCore._write
  (r3_shared/extworld_core.py:229-278; revoked_chain/route_quarantined at 248-252). In G5 mode both dispatch inline right after
  the commit (paladin/deployment.py:177-189; conventional/extsvc.py:29-46).
- F6 Approvals: both re-check, at the CONSUMING commit, that the approver holds the approval capability under the authority in
  force (paladin/core.py:415-418 -> engine/pipeline.py:122-145; conventional/service.py:510-517 -> policy.py:124-132). Neither
  checks the approver's identity revocation. No approval-cancel seam exists (L5 recorded `no_seam` even on r3-harness ladder.py:10).

## 1. 24-cell table

| class | el | classification | Paladin deciding code | conventional deciding code | shared code | one-line reason |
|---|---|---|---|---|---|---|
| A1 | obj | CANDIDATE (M1) | core.py:405-418, engine/pipeline.py:131-134, deployment.py:337, core_g2.py:220-224 | service.py:510-517, policy.py:124-132, pdp.py:69-76 | - | consume-time approval exclusion: Paladin checks edge issuers only when the approval is RECORDED; conventional again at consume -> K-approved edge request commits in Paladin only |
| A1 | ext | CANDIDATE (M1); mode-dependent (D1) | same as obj + core.py:426-429, deployment.py:177-189 | same as obj + service.py:480-489, extsvc.py:29-46 | extworld_core.py:229-278 | M1 on an operation with an external effect (e.g. manufacturing expedite_purchase_order needs approval) adds ext:(system,target) in Paladin only |
| A1 | disc | CANDIDATE (M2, weak) | deployment.py:252-265, 279-283 (AUTH probe), sovchan.py:128-166 | lowevents.py:25-60 (no _g5_pregate), lowreads.py:29-33 | identity.py (token) | conventional subscribe/poll serve under the last-adopted policy; needs a legitimate narrowing of K's read authority inside [t_c,t_d) |
| A1 | prov | BR-NEUTRAL | replay.py:50-115 | replay.py:45-104 | anchor.py | K = principal has no TamperView; prov elements need a tampered record (see A6) |
| A2 | obj | CANDIDATE (M1) | as A1 obj | as A1 obj | - | M1 is an on-behalf-of chain confusion: approver becomes an issuer on Q->requester path after approving |
| A2 | ext | CANDIDATE (M1); mode-dependent (D1) | as A1 ext | as A1 ext | extworld_core.py | as A1 ext |
| A2 | disc | CANDIDATE (M2, weak) | as A1 disc | as A1 disc | - | as A1 disc |
| A2 | prov | BR-NEUTRAL | replay.py | replay.py | anchor.py | no tamper primitive for a principal K |
| A3 | obj | BR-NEUTRAL | core.py:286-291, 405-407, 346-362; capgraph.py:82-92 | service.py:397-434, pdp.py:41-57, authdoc.py:58-65 | authsvc.py (lease) | both re-decide at commit under the freshly fetched lease; redelivery returns the recorded decision, no second effect; strict expiry in both |
| A3 | ext | BR-NEUTRAL | extdispatch.py:68-111 | extout.py:109-152 | extworld_core.py:248-269 | intents committed before the authority change are dispatched by both (decision final at commit, R28-1); expiry/uses enforced server side |
| A3 | disc | CANDIDATE (M2) | deployment.py:256-259 probe + sovchan.py:59,143-166 | lowevents.py:49-60, 77-80 (`self._policy`) | - | after a publish that removes K's read grant, a K poll before any other conventional governed call is projected under the OLD policy |
| A3 | prov | BR-NEUTRAL | replay.py | replay.py | anchor.py | stale authority replays are not provenance tamper |
| A5 | obj | BR-NEUTRAL | - | - | - | probes are reads; no world object changes |
| A5 | ext | BR-NEUTRAL | - | - | - | no external intent from reads |
| A5 | disc | CANDIDATE (M2) | as A3 disc | as A3 disc | disclosure.py (forms only) | same mechanism; conventional larger |
| A5 | prov | BR-NEUTRAL | sovprov.py | lowprov.py | - | prov_* disclosures count as disc, not prov; both prov_* paths go through the AUTH-probed low channel |
| A6 | obj | BR-NEUTRAL | core.py:109-125, 454-469, core_g2.py:321-336; histledger.py:101-111 | histledger.py:50-118 | histstore.py | tampered approval/idempotency/authority records are skipped or refused in both (lost progress, not BR) |
| A6 | ext | BR-NEUTRAL (safety-record difference D5) | extoutbox.py:19-50 in HistoryStore (core.py:97-98) | extout.py:24-36 in world DB (variant.py:21) | extworld_core.py:259-269 | a tampered Paladin outbox can be resubmitted, but the cap's target/payload/uses bound the applied rows |
| A6 | disc | BR-NEUTRAL | - | - | - | K = evidence store contains no principal |
| A6 | prov | CANDIDATE (M3, hypothesis) | continuity.py:142-182, core_g2.py:308-319, replay.py:50-115 | g5journal.py (world DB), g5svc.py:170-197 | anchor.py | Paladin rebuilds a missing anchor entry from the `led/pend/<rid>` record in the attacker-controlled HistoryStore; conventional from a world-DB journal |
| A7 | obj | BR-NEUTRAL | core.py:426-429 (reply never changes decision) | extsvc.py:29-46 | extobs.py | an adapter reply never changes a committed decision or a world object in either |
| A7 | ext | SHARED | extdispatch.py:33-42, 91-111 | extout.py:56-62, 121-152 | extworld_core.py:229-278, extcap.py:84-128, opplane.py:98-104 | identical caveats/uses; L1 quarantine_route and every refusal decided server side |
| A7 | disc | BR-NEUTRAL | - | - | - | K = adapter contains no principal |
| A7 | prov | BR-NEUTRAL | extdispatch.py:96 (envelope text) | extsvc.py:18-27 | anchor.py | adapter sees envelopes but cannot write the anchor or history |

Counts: CANDIDATE 9 (A1-obj, A1-ext, A1-disc, A2-obj, A2-ext, A2-disc, A3-disc, A5-disc, A6-prov), BR-NEUTRAL 14, SHARED 1, UNKNOWN 0.
Mechanisms: M1 = A1/A2 obj+ext; M2 = A1/A2/A3/A5 disc; M3 = A6 prov.

## 2. CANDIDATE mechanisms and scenarios

### M1 - approval exclusion evaluated at different times (A1 obj/ext, A2 obj/ext). Predicted: BR_P > BR_C.
Rule text: PROT-H24.md:67-68 "the approver ... must not be Q or any issuer on ANY edge path from Q to the requester that exists at
the approval's commit point". The two variants read "the approval's commit point" differently *(fact, from code)*:
- Paladin checks the exclusion ONLY when the approval is recorded: deployment.py:337 `c.excluded_approvers(requester, obo)` =
  static chain + capgraph.chain_issuers (core_g2.py:220-224). At consume time (core.py:415-418 -> eng.approve ->
  engine/pipeline.py:131-134) it only checks that the approver's STATIC chain does not intersect the proposer's, where the proposer of
  an edge request is Q (core.py:196-200 returns Q as the principal). Edge issuers are not re-checked.
- Conventional checks at record time (service.py:550-551) AND at consume time (service.py:512-514: `approval_forbidden(subject, obo)`
  recomputed from the edges in force, pdp.py:69-76, policy.py:128-131).
Scenario (all primitives frozen: H23 approve, H24 delegate, legitimate workload): overlay principals Q (root), K (compromised agent,
holds a redelegable edge e1: Q->K, and the approval capability of op P), R (legitimate agent).
1. t1 in [t_c,t_d): K calls approve(op=P, args=A, requester=R, on_behalf_of=Q). No path Q..R exists yet -> excluded = {Q, R}; both
   variants record the approval.
2. t2: K delegates e2: K->R, parent e1, scope covering P/A (attenuated, legal in both: capgraph.py:111-158, authdoc.py:73-111).
3. t3: R (legitimate workload, or any later redelivery of R's planned request whose args the task author knows) calls P(A) obo Q via
   path e1,e2. Approval required.
   - Paladin: claim_approval finds K's approval (ledger fp matches), eng.approve(K) passes (K's static chain disjoint from Q's) ->
     COMMIT. Request is tainted (path contains e2 created by K, approval given by K) -> obj:<refs of P> (+ ext:(S,target) if P has an
     external effect) enter BR_P.
   - Conventional: approval_forbidden(R, Q) = {Q, K} -> can_approve(K) false -> DENIED approval_required, no effect. BR_C lacks them.
Window: before detection. After detection the residual is the same mechanism (K's approval stays open; L5 has no seam; L1 does not
touch stored approvals, F2). L2 contains it in both (K loses the approval capability, F6); L3 contains it in both (e2 revoked).
So the difference is in the attack window plus the TAIL until L2 (rung reached is the same in both).
Oracle note: the oracle's reading of PROT-H24 s3 decides whether Paladin's commit is also a FORBIDDEN effect (safety regression,
s8.5) or only a tainted one; either way it is a BR element because the path contains K-derived elements (s1.4).
Requirement on the task: R's request with the exact args must actually be issued after step 2 (the approval binds exact inputs).

### M2 - conventional subscribe/poll skip the AUTH lease gate (A1/A2 disc weak; A3/A5 disc). Predicted: BR_C > BR_P.
- The dependency graph makes every read decision depend on AUTH (spec/gate5/dependency-graph.json surfaces.read.decision = [AUTH]).
- Paladin: every low channel, subscribe and poll included, goes through deployment._low (deployment.py:252-265, 279-283), which probes
  AUTH and adopts the newest lease (continuity.py:74-89, 57-72) BEFORE the view is built from the authority now in force.
- Conventional: read_object/list/query/prov_* go through lowreads._low with _g5_pregate("read") (lowreads.py:29-33 -> g5svc.py:101-122),
  but subscribe and poll (lowevents.py:25-60) call neither _g5_pregate nor _g5_auth; poll builds before/after views with
  `self._policy` (lowevents.py:77, 98), i.e. the version adopted at the LAST governed call.
Scenario: K (principal) subscribes to type T while authorised; the authority service publishes a version that removes K's read
grant on T (legitimate narrowing in the workload, H29 F6-stale style publish, or for A3 the very version change the class is about);
a write to an object of T commits; K polls before any other conventional governed call or read (the attacker controls K's call
timing; same tick as the publish suffices). Conventional emits the create/update event with props under the old policy ->
disc:<T:key> outside the oracle low view. Paladin adopts the new lease first and emits nothing.
Containment: for K = principal L1 (identity revoke) stops poll in both (F1), so the difference lives in [t_c, t_d) and needs a
legitimate publish there. That is why A3/A5 are rated stronger (the class's attack IS stale/revoked authority or a probe through the
subscription surface) and A1/A2 weak (needs an incidental publish). The gap closes at the next conventional governed call: a dense
legitimate workload narrows it to sub-tick ordering, so the task author must place the poll right after the publish.

### M3 - Paladin trusts a HistoryStore record when it completes a missing anchor entry (A6 prov). Predicted: BR_P > BR_C. *(hypothesis)*
- Paladin H29 with a history: the pre-commit decision record is written to the HistoryStore `led/pend/<rid>` (core_g2.py:308-315) and,
  for a commit whose anchor entry is missing (crash at CP2 / ANCHOR reply lost, H29 fault-plane primitives), complete_anchors
  (continuity.py:142-182) rebuilds the decision from that record (sub, obo, op, args, path, evidence, doc), binds the real world rows
  and appends it to the anchor via finish(). It runs at the first call after heal (guarded() continuity.py:134-135, _dispatch, _reconcile).
- Conventional keeps the equivalent journal in the world DB (conv_journal, g5journal.init(h) on the world handle, service.py:106-107;
  completion g5svc.py:170-197), which an A6 attacker (K = mutable evidence store = HistoryStore) does not control.
Scenario: a legitimate commit C loses its anchor entry (fault); K edits `led/pend/<C>` (e.g. a different evidence set or authority
document, args kept so the world rows still match) before the heal; Paladin anchors the forged envelope; replay(C) (R3) then checks
envelope vs anchored root, chain and artifact digests (replay.py:1-5, 50-115), all self-consistent with the forged record -> VERIFIED
-> prov:<C> in BR_P (and recovery_incorrect if R3 trusts it). Conventional: journal untouchable -> correct envelope.
Not established: whether Paladin's authority re-check in replay (paladin/authreplay.py) or the args_digest/rows binding rejects a
forged doc/evidence; whether H27/H29 tasks combining a CP2 fault with a TamperView edit are inside one H30 task's primitives. This
is the cell I am least sure about.

## 3. UNKNOWN cells and what is missing
No cell is classified UNKNOWN, but these facts are missing at HEAD and can flip cells:
- U1 Deploy mode for H30 is not frozen (no runner at HEAD). If H30 ran WITHOUT authority_source, Paladin would not dispatch inline
  (deployment.py:181 `if not self._h29 ... return res`) while conventional always does (extsvc.py:38-40). Then every ext cell where K's
  intent commits before t_d becomes mode-dependent (D1). L2 would also not exist in that mode, so the ladder as frozen needs G5 mode.
- U2 Whether H30 deploys with history + anchor (H27). M3 and D5 exist only then (Paladin's ledger and outbox move into the HistoryStore,
  core.py:97-98). Without a history, M3 is void.
- U3 The oracle's reading of PROT-H24.md:67-68 ("the approval's commit point") decides whether M1's commit is forbidden or only tainted
  (BR either way).
- U4 Whether the task DSL lets a task place an authority publish in [t_c, t_d) (needed for M2 in A1/A2; A3 tasks need it by definition).
- U5 M3: whether paladin/authreplay.py or the envelope's row binding rejects a forged pend record (not read in full).

## 4. Behavioural differences that touch effects, retries, disclosures or provenance (completeness list)
Each item: Paladin vs conventional, file:line, and its BR status.
D1 Inline dispatch: Paladin only in G5 mode (deployment.py:177-189, gate at 181); conventional always after a fresh commit
   (extsvc.py:29-46). BR-relevant only outside G5 mode, and only if a later rung or expiry can stop a deferred intent: at HEAD no
   variant re-checks authority/identity at dispatch (F5) and L4 names chains only from the ExternalWorld audit (r3-harness
   ladder.py:9), i.e. only for caps that were already submitted, so a deferred intent is NOT stopped by L1-L4; it is stopped only if it
   expires (not_after_tick) before the harness calls dispatch_pending. Direction: P <= C, caused by the harness's dispatch_pending
   schedule and not by the architecture. (Same point as the side agent's note; its "the operator gets time to revoke" holds only once
   G6 dispatch-time re-authorization lands, s6.)
D2 Envelope wait: Paladin does not submit an intent until its envelope is provable from the anchor (extdispatch.py:81-83,
   core.py:471-481); conventional submits with envelope "" when none is found (extsvc.py:18-27). Timing only; anchor faults are A9.
D3 Expiry at dispatch: conventional skips expired intents (extout.py:109-112); Paladin keeps submitting and the server refuses
   `expired` (extdispatch.py:68-71; extworld_core.py:265-266). Extra refused audit rows in Paladin, no applied rows. BR-neutral.
D4 DependencyUnavailable during submit: Paladin never counts it as an attempt (extdispatch.py:103-106); conventional counts it only
   when no G5 guard is attached (extout.py:138-145: `continue` only inside `if self.guard`). In G5 mode equal. BR-neutral (cap bounds).
D5 Outbox / outcome / pre-commit journal location: Paladin's live in the request ledger, i.e. the HistoryStore when a history is given
   (core.py:97-98, extoutbox.py:3-6, core_g2.py:308-319); conventional's live in the world DB (variant.py:20-21, extout.py:24-36,
   service.py:104-107). An A6 attacker can reset Paladin attempts/replies (resubmission, bounded by the cap), delete an intent (lost
   effect: smaller BR, lost progress) or set an outcome to RECONCILED_SUCCESS that the monotone rule then keeps
   (extdispatch.py:138-139) -> false_reconciled_success in Paladin only (safety-record class, not a BR element). M3 is the prov part.
D6 Circuit breaker per pass: conventional skips a system after one DependencyUnavailable in a dispatch pass (extout.py:124-142);
   Paladin keeps trying every intent (extdispatch.py:73-85). Timing only.
D7 Approval exclusion at consume time (M1).
D8 Approval selection: Paladin claims the OLDEST open approval for the fingerprint and, if that approver now lacks the capability,
   refuses the request without trying the next one (ledger.py:109-123; core.py:415-418, 442-444); with a history, unverifiable records
   are skipped (histledger.py:101-111). Conventional iterates every open approval and consumes the first that is valid now
   (service.py:513-516). After L2 narrows K, Paladin can deny a request that also holds a legitimate approval: lost safe progress
   (s1.8), not BR.
D9 Tampered/missing approval record: conventional raises LedgerUnresolved -> request UNAVAILABLE (histledger.py:81-83); Paladin skips
   the record (histledger.py:105-108) and uses another valid one. Progress, not BR.
D10 subscribe/poll lease gate (M2). Also: Paladin's tools() listing does no AUTH probe (deployment.py:159-170); conventional's tool
   listing path is not gated either (tools.py:25-27). Tool names only, not protected refs: not a disc element.
D11 Unknown-principal checks in delegation: Paladin refuses an unknown ISSUER (capgraph.py:127-132); conventional checks only that the
   child is known (authdoc.py:88-89) and the root grant via root_may_delegate. Equal under the frozen narrowing (grants removed,
   principals kept, r3-harness ladder.py:7); would differ if a narrowing removed K's principal entry (conventional K could still
   re-delegate under a parent edge it holds).
D12 G5 refusal shapes: conventional answers an input error with INVALID before authentication (g5svc.py:52-60, 80-99); Paladin only for
   an authenticated caller (continuity.py:103-106). Error-shape only; no protected ref.
D13 Redelivery of a committed request: both answer the recorded decision (paladin/core.py:229-247; conventional g5svc.py:199-230); in
   legacy mode Paladin re-checks authority now (core.py:360-361) and conventional decides before reading the ledger (service.py:417-434).
   No second effect in either. BR-neutral.
D14 Anchor completion trigger: Paladin completes missing anchor entries from history records at the first call after heal
   (continuity.py:134-135, 142-182); conventional from the world-DB journal when the ANCHOR probe succeeds (g5svc.py:144-157, 187-197).
D15 Paladin `_approval_check` (core.py:454-469) verifies an approval against the anchor (anchored approve decision, not consumed);
   conventional relies on world-log approval/approval_used marks (histledger.py:68-95). Both block reuse; different trust roots.

## 5. Confidence and least-sure cells
- High *(fact)*: F1 (identity revocation is shared and checked every call in both), F5 (caps and server-side enforcement equal),
  A7-ext SHARED, D1 (inline dispatch is G5-only in Paladin).
- Medium-high *(model)*: M1 exists in the code as described; the scenario needs only approve + delegate + one legitimate request
  with known args. Not run.
- Medium *(model)*: M2 - the code path is clear, but the BR gap depends on the task placing a poll between a publish and the next
  conventional governed call; a dense workload may close it.
- Low *(hypothesis)*: M3 (U5 unverified). Also the A6 obj/ext BR-NEUTRAL calls rest on the cap bounds and H27 parity, not on an
  exhaustive read of both replay paths.
- BR-NEUTRAL cells for A3 obj and A1/A2 obj outside M1 rest on the H23-H26 parity of two independently written decision paths
  (same frozen rules); I did not prove equivalence clause by clause.

## 6. G6-only seams (unmerged branches; not analysed as HEAD)
- r3-paladin adds paladin/revoke.py (consults the revocation list at entry, effect time, graph derivation, approval consume and
  outbox dispatch; ablation switch PALADIN_G6_DISABLE l1..l7), taint.py, edits to capgraph/core/extdispatch/ledger.
- r3-conv adds conventional/revocation.py (same list, E30-1/3/5), exthalt.py (adapter-side halting: dispatch-time re-authorization
  callback + halt on observed revoked_chain/route_quarantined), taint.py, pdp.py/service.py/extout.py edits.
- r3-harness adds h30 ladder.py (L3 uses the path-root issuer's token and skips edges rooted at K; L4 chain ids from the ExternalWorld
  audit; L5 `no_seam`), runner/taskplay, r3_oracle/incident.py.
- Once these land, F2 and D1 change: deferred/queued K intents become stoppable by L1 in both, M1/M2/M3 are untouched by the
  listed file names but should be re-checked on the merged candidate.

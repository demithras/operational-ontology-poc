# Protection specification H25 - constitutional authority topology (both variants)

FROZEN 2026-10-08 (author decisions 2026-10-08; rulings in spec/gate3/OPEN-QUESTIONS.md). Requirement-level: WHAT must hold, not HOW.
This file is the ONE place the H25 rules are written; r3_oracle/constitution.py, both variants and r3_harness/h25
implement exactly this text. Builder briefs point here and never restate or amend it. Attack class A4 (authority
topology conflict) plus A3/A8 where emergency expiry and commit order meet. Contract: hypotheses/h25/contract.json.
Protocol: PROTOCOL-P1e.md (P1e-1..P1e-4). Depends on PROT-H23 (base authority) and PROT-H24 (commit point, clock, marks).

## 0. The boundary this gate tests (procedural vs discretionary)

- PROCEDURAL authority = who may decide what, when, by which rule: bodies, membership, jurisdiction, hierarchy,
  quorum, recusal, review/appeal windows, precedence between competent bodies, bounded emergency authority. It is
  computed from the frozen governance document (s1) plus commit-ordered actions (s3). Both variants and the oracle
  compute it; it must be EQUAL.
- DISCRETIONARY merit = the content of a judgment (concur/dissent, uphold/overturn, and an opaque `merit` string).
  It enters ONLY as an attributable `judge` action by a principal (s3.2). No component computes it. Where the procedure
  needs a judgment that has not been supplied, the outcome is AWAITING (never ALLOWED/DENIED), unless the governance
  document itself declares a procedural lapse rule for that matter (s2.5) - then the outcome cites `lapse`, never a judgment.

## 1. Governance document `r3-governance-1` (data; schemas/governance-spec.schema.json; validate_governance, P1e-1)

```
{ "spec": "r3-governance-1", "model": <id>, "domain": <domain>,
  "bodies":  [ { "id", "members": [principal...], "rule": RULE, "rank": int } ],
  "superior": [ [lower_body_id, upper_body_id] ... ],              # hierarchy, must be acyclic
  "matters": [ { "id", "scope": SCOPE, "competent": [body_id...], "concurrence": bool,
                 "review": { "by": body_id, "window": int } | null,
                 "on_absent": "await" | { "lapse": "allow" | "deny", "after": int } } ],
  "precedence": [ "specialis" | "superior" | "rank" ... ],          # ordered tie-break list, may be []
  "emergency": { "matter": matter_id, "max_duration": int, "ceiling": SCOPE, "grantees_from": body_id } | null }
RULE  = {"kind": "single"} (body has exactly 1 member) | {"kind": "quorum", "k": int, "recuse": ["requester"]|[]}
SCOPE = {"operations": [op...], "resources": [{"type": T, "keys": [k...] | null}...]}   # PROT-H24 s1 scope, same coverage
```
Static rules (validate_governance raises ValueError; a refused document changes nothing): unique ids; every member is a
principal of the auth spec in force and NOT an H23 static delegate; 1 <= k <= len(members); `single` bodies have one
member; `superior` acyclic and names known bodies; every matter names >= 1 competent body; review.by is not one of the
matter's competent bodies; window >= 1; lapse.after >= 1; the emergency matter exists and its scope only contains the
pseudo-operation `emergency:declare`; ceiling ops exist in the ops spec; `precedence` has no duplicates.
Domain neutrality: the document is the only place model-specific facts live. Model ids, body ids and principal ids are
opaque strings to every decision path (R25-6).

## 2. Procedural evaluation (the oracle function; variants must agree with it)

2.1 Matter of a request. A request (op, R) (R as PROT-H24 s1) is GOVERNED iff some matter's scope covers it
(scope coverage, PROT-H24 s1). Ungoverned requests are decided exactly as PROT-H23/H24 (H25 adds nothing).
2.2 Competent body. Candidate bodies = union of `competent` of every matter covering the request. If the covering
matters have `concurrence: true`, ALL their competent bodies must allow (s2.4). Otherwise exactly one body decides,
chosen by `precedence` applied in list order to the candidate set; each criterion keeps only the maximal elements:
  - `specialis`: keep bodies whose matter scope is NOT a strict superset of another candidate's matter scope
    (scope_subset strict: subset and not equal);
  - `superior`: keep bodies with no candidate strictly above them in the transitive `superior` relation;
  - `rank`: keep bodies with the greatest `rank`.
After the list, if more than one body remains -> refusal DENIED `precedence_unresolved` (explicit; nothing decides).
Two matters covering the same request with different `concurrence` flags -> INVALID `matter_conflict` at propose.
2.3 Eligible judges. For a case at a stage: the body's members, minus the requester if `recuse` contains "requester".
A body whose eligible set is smaller than k is impossible -> the stage is AWAITING forever unless a lapse applies.
2.4 Stage outcome from judgments (values: decision stage `concur|dissent|abstain`; review stage `uphold|overturn|abstain`).
Counted judgment = the FIRST valid judge action of each eligible member for that (case, stage) in commit order.
  - single: the holder's judgment: concur -> ALLOW, dissent -> DENY, abstain/none -> AWAITING.
  - quorum k over n eligible: concur >= k -> ALLOW; dissent > n - k -> DENY; else AWAITING.
  - concurrence: every competent body ALLOW -> ALLOW; any DENY -> DENY; else AWAITING.
  - review stage on body V: uphold >= k_V -> UPHELD; overturn >= k_V -> OVERTURNED; else AWAITING (single: holder).
  The stage outcome is fixed at the commit point of the judgment that first makes it non-AWAITING (decided_seq,
  decided_tick). Later judgments for a decided stage are INVALID `stage_closed`.
2.5 Lapse. A matter with `on_absent: {lapse: X, after: d}`: if the decision stage is still AWAITING at a transaction
with tick >= propose_tick + d, the stage outcome is X with basis `lapse` (fixed at that transaction). `await` never lapses.
2.6 Review/appeal. If the matter has `review`, a decided case may be appealed (s3.3) while tick < decided_tick + window.
FINAL outcome: no review configured -> the decision outcome, final at decided_seq. Review configured: not appealed and
tick >= decided_tick + window -> the decision outcome; appealed -> review UPHELD keeps it, OVERTURNED flips
ALLOW<->DENY, AWAITING -> not final. A lapsed decision is reviewable exactly like a judged one.
2.7 Basis. The basis of a final outcome = the ordered list (commit order) of the request_ids of EVERY counted judgment of
the stages that produced it (decision stage of each deciding body, then review stage if appealed); [] for lapse.
"rule" = one of `decision | review | lapse | emergency`.

## 3. Actions (one entry point, P1e-2 `Deployment.constitutional`) and the frozen CHECK ORDER

Every action is a mutating request: token-bound, request_id idempotent (PROT-H23 R5), thread-safe, arm_crash applies,
and it commits as ONE world transaction carrying exactly one `governance` mark (P1e-3). First failure wins, in order:
3.0 Common: token invalid -> DENIED `token`; action fails its schema (P1e-2) -> INVALID `schema`; no governance
    document in force -> INVALID `no_governance`.
3.1 propose {case, operation, args, on_behalf_of}: duplicate case id -> INVALID `duplicate_case`; request schema
    (E-9 rules) -> INVALID `schema`; not governed -> INVALID `not_governed`; `matter_conflict`; base authority of the
    requester for (op, args) per PROT-H23/H24 -> DENIED `no_authority`; precedence (2.2) -> DENIED `precedence_unresolved`.
    OK {"case", "bodies": [deciding body ids, sorted]}. propose never checks object existence or business rules.
Case visibility (binding with PROT-H26 s1.3/3.1): in 3.2-3.5, "unknown case" includes a case the caller cannot see
(callers who see a case: its requester and the members of its competent and reviewing bodies); such calls get exactly
INVALID `unknown_case`, never a party/eligibility refusal.
3.2 judge {case, stage, value, merit}: unknown case -> INVALID `unknown_case`; judge not eligible for that stage
    (not a member, recused, or stage = review and no appeal) -> DENIED `not_eligible`; stage already decided ->
    INVALID `stage_closed`; this member already judged this stage -> INVALID `already_judged`; review stage after
    the review outcome is fixed -> INVALID `stage_closed`. OK {"case", "stage"}. `merit` is an opaque string stored
    and returned verbatim; it never influences any outcome (R25-3).
3.3 appeal {case}: unknown case -> INVALID `unknown_case`; matter has no review -> INVALID `not_reviewable`; decision
    stage not decided -> INVALID `not_decided`; caller is not the requester and not a member of a deciding body ->
    DENIED `not_party`; already appealed -> INVALID `already_appealed`; tick >= decided_tick + window -> DENIED
    `window_closed`. OK.
3.4 execute {case}: unknown case -> INVALID `unknown_case`; caller != requester -> DENIED `not_requester`; already
    executed -> stored result (idempotent by case: one effect per case, R5 semantics); the decision stage or an
    appealed review stage is AWAITING at this commit (after applying any due lapse, s2.5) -> DENIED `oracle_needed`;
    decided, not appealed and tick < decided_tick + window -> DENIED `not_final`; final DENY -> DENIED `case_denied`; base authority re-checked at THIS commit
    (PROT-H24 s3 freshness) -> DENIED `no_authority`; then the operation runs exactly as PROT-H23 (existence, rules,
    preconditions, approvals) with its usual outcomes. OK commits the effect plus the `commit` mark and the governance mark.
    Ordinary call_tool/direct of a GOVERNED request (no case) -> DENIED `case_required`, zero effects.
3.5 Emergency. declare = propose with operation `emergency:declare` and args {"emergency": id, "scope": SCOPE,
    "expires_at": int, "grantees": [principal...]} on the emergency matter; it is decided like any case (s2) and
    becomes ACTIVE at the commit point where its final outcome is ALLOW. Extra checks at propose, after 3.1's order:
    (`emergency:declare` is a pseudo-operation with the frozen input schema of P1e-2; base authority = an allow grant
    on `emergency:declare` per PROT-H23) scope not a subset of `ceiling` -> DENIED `scope_amplification`; expires_at > propose_tick + max_duration ->
    INVALID `emergency_too_long`; a grantee not a member of `grantees_from` -> DENIED `not_grantee`.
    act {emergency, operation, args, request_id via the action}: emergency unknown or not ACTIVE at this commit ->
    DENIED `emergency_inactive`; caller not a grantee -> DENIED `not_grantee`; request not covered by the emergency
    scope -> DENIED `out_of_emergency_scope`; tick >= expires_at -> DENIED `emergency_expired`; a deny grant matching
    the caller -> DENIED `no_authority`; then PROT-H23 operation semantics. An ACTIVE emergency replaces the case
    procedure ONLY for its grantees, its scope and its window. end {emergency} by any member of the declaring body ->
    inactive for every later commit. Emergency authority is non-delegable (H24 edges never derive from it) and leaves
    no residual: after expiry/end every request is decided exactly as if the emergency had never existed (R25-4).
3.6 set_governance(doc) (P1e-2): validate_governance; replaces the document for every later commit; cases opened
    earlier keep their case id and judgments but are re-evaluated under the new document from that point on (no
    grandfathering). Cases/judgments/appeals/emergencies change only through 3.1-3.5 (E-5 lesson: the document carries
    no case state; any such key is a schema error).

## 4. Clock and commit (inherits PROT-H24 s4)

Commit point = world_log seq of the action's transaction; commit tick = tx.tick. Windows, lapse and emergency expiry
are strict (`tick >= bound` is outside). The winner rule and linearizability of PROT-H24 s4 apply to every pair of
constitutional actions and effects (e.g. execute || appeal, act || end, judge || set_governance).

## 5. Requirements

| Id | Requirement |
|---|---|
| R25-1 procedural equality | For every action, the variant's status class (OK / refusal class of s3) and its governance mark equal the oracle's at that commit point; every final outcome and basis equal the oracle's. |
| R25-2 no effect without legitimacy | No governed effect commits unless the oracle's final outcome at its commit point is ALLOW (or an ACTIVE emergency covers it, s3.5). |
| R25-3 no fabricated judgment | No mark, outcome or basis cites a judgment that was not supplied by an eligible member's judge action; no ALLOW/DENY is produced where the oracle says AWAITING without lapse; `merit` never changes an outcome. |
| R25-4 bounded emergency | No act commits outside the emergency's scope, grantees or [activation seq, min(expires_at, end)); nothing granted by an emergency survives it. |
| R25-5 explicit unresolved | Every procedurally undeterminable outcome is an explicit refusal (`oracle_needed`, `precedence_unresolved`, `not_final`) with zero effects; no fallback to base authority for a governed request. |
| R25-6 genericity | The same decision code executes every registered governance model on both domains; no decision path branches on a domain name, model id, body id, principal id or other fixture identity (domain-branch audit, ORACLE-AND-HARNESS-G3 A5). |
| R25-7 durability and replay | Cases, judgments, appeals and emergencies survive crash/restart (marks are the record); request_id idempotency per PROT-H23 R5. |
| R25-8 safe progress | Every execute/act the oracle allows in every linearization consistent with real time commits OK (floor 1.0, s7). |

## 6. Mutants (frozen in r3_shared.mutants.KNOWN["H25"])

- `precedence_inverted`: the precedence list is applied with each criterion keeping the MINIMAL elements.
- `quorum_weakened`: a quorum body allows at k-1 concurring judgments.
- `emergency_no_expiry`: emergency activity ignores expires_at (end still works).
- `merit_autofill`: a stage that is AWAITING at execute is treated as ALLOW with a synthesized basis (the classic
  "missing judgment defaults to yes"), in the place a real implementation computes the final outcome.
- `domain_privilege_branch` (extra, justified: the contract's audit clause must be proven non-vacuous): the decision
  path grants `execute` without a case when the deployment's domain is "project" and the requester's id ends in "-1".
  Must be killed by the domain-branch audit (static scan OR metamorphic renaming), not only by the corpus.
Each of the first four must be killed by the corpus (>= 1 classified case), not by a unit test.

## 7. Safe-progress and coverage floors (proposed; author ruling Q3 in OPEN-QUESTIONS)

(i) legit progress = OK / execute+act calls allowed in every consistent linearization: must be 1.0;
(ii) coverage per governance model: >= 1 case of each outcome rule (decision, review, lapse, emergency where the model
has them) and of each refusal class in s3 reachable in that model; (iii) >= 1,000 cases with missing judgments
(oracle_needed) and >= 500 precedence conflicts in total. Any floor unmet -> the variant cannot be SUPPORTED (INCONCLUSIVE).

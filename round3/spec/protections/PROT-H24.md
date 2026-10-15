# Protection specification H24 - delegation, revocation and expiry under concurrency (both variants)

FROZEN 2026-10-07 (author decisions 2026-10-07 #2; rulings in spec/gate2/OPEN-QUESTIONS.md). Requirement-level: WHAT must hold, not HOW. This file is the ONE place the rules below are
written; the oracle (r3_oracle/authority_v2.py), both variants and the harness implement exactly this text. Builder briefs
may point here but never restate or amend it. Attack classes: A3 (stale/revoked authority), A4 (topology conflict),
A8 (concurrency/replay). Contract: hypotheses/h24/contract.json (frozen). Protocol: PROTOCOL-P1d.md (r3_shared).

## 1. Authority graph v2 (frozen semantics)

Layer 0 - base authority: the v1 auth spec (`principals`, `grants`, static `delegations`, `delegated_by`) evaluated
exactly as PROT-H23 (unchanged). `base(P, op, resources)` = r3_oracle.authority.decide(P, None, op, resources, spec).

Layer 1 - capability edges (new). An edge is
`{id, issuer, child, parent, scope: {operations: [op...], resources: [{type: T, keys: [k...] | null}...]},
  expires_at: int | null, redelegable: bool, issued_at: int}`.
- `parent` is the id of the edge the issuer delegates FROM, or null (a ROOT edge: the issuer delegates from its own base
  authority). The issuer of a non-root edge must be the `child` of its parent edge.
- `root(e)` = the issuer of the root edge at the top of e's parent chain. `path(e)` = the edges from root edge to e.
- `depth(e)` = len(path(e)). Frozen maximum: `max_delegation_depth` = 8 (spec field; the corpus uses depth 1..8 and
  >= 25% of edge-backed requests use depth >= 4).
- Principals with a non-null `delegated_by` (H23 static delegates) may neither issue nor receive edges (INVALID
  `static_delegate`). This keeps the H23 rule untouched and the two mechanisms disjoint.

Scope coverage. A request (op, R) with R = the (type, key) pairs of its resource-typed inputs is IN scope s iff
op is in s.operations AND every (T, k) in R is matched by some entry of s.resources with type T and (keys null or k in
keys). A request with no resource inputs is in scope iff op is in s.operations.
Scope subset (attenuation). s_child is a subset of s_parent iff operations(child) is a subset of operations(parent) AND
every child entry (T, K) has a parent entry (T, K') with K' null, or K non-null and K a subset of K'. Purely syntactic,
decidable, no clamping.

## 2. Issuance (`Deployment.delegate`) - explicit failure, never clamp, never accidental grant

Evaluated atomically at the delegation's commit point (section 4). In this order, first failure wins:
1. Token invalid -> DENIED `token`. Malformed edge (schema) -> INVALID `schema`. Duplicate edge id -> INVALID `duplicate_edge`.
2. issuer == child, or child already appears as the issuer of any edge in path(parent) or as root(parent)
   -> INVALID `delegation_cycle`.
3. issuer or child is a static delegate -> INVALID `static_delegate`. Unknown child principal -> INVALID `unknown_principal`.
4. Non-root: parent missing -> INVALID `unknown_parent`; issuer != parent.child -> DENIED `not_parent_holder`;
   parent not VALID at this point (revoked, expired, or an ancestor invalid) -> DENIED `parent_invalid`;
   parent.redelegable is false -> DENIED `not_redelegable`; depth > max -> INVALID `depth_exceeded`.
5. Attenuation: non-root: scope not a subset of parent.scope -> DENIED `scope_amplification`;
   expires_at later than the parent's effective expiry (null counts as infinity) -> DENIED `expiry_amplification`.
   Root: every op in scope must be matched by at least one allow grant with `delegable: true` whose principal selector
   can match the issuer (static upper bound, r3_shared.authspec.allowed_operations semantics) -> else DENIED
   `scope_amplification`. (Per-request coverage of a root edge is re-checked at use, section 3.)
6. expires_at not null and expires_at <= the commit tick -> INVALID `already_expired`.
Success: OK {"edge_id"}; the edge exists from its commit point on. Refusal: zero authority change.

## 3. Use (effect eligibility) - evaluated at the effect's commit point

A path p (root edge .. e with e.child == subject) is VALID for request (subject, on_behalf_of=Q, op, R) at commit
point c with commit tick t iff ALL hold:
(a) root(p) == Q (a request relying on delegated authority names the root principal as on_behalf_of; actor_for_rules = Q);
(b) every edge on p is committed before c and not revoked before c (section 4 order);
(c) t < expires_at for every edge on p with non-null expires_at (strict: an edge with expires_at = 10 is usable at tick 9,
    not at tick 10);
(d) the request is IN scope of EVERY edge on p (intersection, not just the last edge);
(e) base(Q, op, R) allows under the authority spec in force at c (root re-check; a set_authority that removes Q's grant
    invalidates every path rooted at Q);
(f) no deny grant matches the subject or any issuer on p for (op, R).
Decision for a request with on_behalf_of = Q:
- subject is an H23 static delegate -> the H23 rule, unchanged (edges never apply).
- else ALLOWED iff some VALID path exists. Several valid paths -> allowed (any one suffices; deterministic, set-based).
  No valid path -> DENIED `no_valid_path`. Paths through a cycle are impossible by construction (section 2.2).
With on_behalf_of null: base(subject, ...) only; edges never apply. Business rules, preconditions and approvals are
then evaluated exactly as PROT-H23 with actor_for_rules = Q (edge request) or the subject.
Approvals for an edge request: the approver must differ from the requester and must not be Q or any issuer on ANY
edge path from Q to the requester that exists at the approval's commit point (extends "outside the delegation chain").

## 4. Clock model and commit boundary (frozen; the one-legitimate-outcome rule)

- Time is the shared r3_shared.clock.LogicalClock (integer ticks). Only the harness advances it. Variants never read
  wall-clock time in any decision path.
- COMMIT POINT. Every authority mutation (delegate, revoke, set_authority) and every effect commit happens inside ONE
  world-store write transaction opened with `WorldHandle.transaction(tag=...)` (PROTOCOL-P1d). The world store
  serialises write transactions; its append-only `world_log` gives every committed transaction a unique `seq`.
  A transaction's COMMIT POINT is its seq. Its COMMIT TICK is `tx.tick`, the clock value the WorldHandle read when the
  transaction acquired the write lock; it is stamped on every log row of the transaction by r3_shared, not by the variant.
- Authority mutations are recorded with `tx.mark("authority", <kind>, payload)` in that transaction. An authority
  mutation without a mark did not happen (the oracle ignores unmarked state; using it is a stale/forged path).
- Revocation boundary: an edge revoked at seq r is invalid for every transaction with seq > r. Expiry boundary: an
  edge with expires_at = x is invalid for every transaction with tick >= x. set_authority at seq s governs every
  transaction with seq > s.
- WINNER RULE (revoke vs execute, expiry vs execute, delegate vs revoke-parent): the order of the two transactions in
  world_log decides, and given that order exactly one outcome is legitimate. The variant may choose the order of
  REAL-TIME-OVERLAPPING calls; it may NOT contradict real time: if call X returned before call Y was invoked
  (harness happens-before record), X's commit point must precede Y's (linearizability). A revoke that returns OK
  before its commit point (acknowledged early) violates this rule even if no effect slipped through in that run.
- A revoke that returns anything but OK changed nothing. A crash at `after_commit` of a revoke leaves it effective;
  at `before_commit` leaves it absent. Revocations and edges survive crash()/restart() (durable before OK).
- Retry: a request_id that committed before a revocation returns its stored result and never a second effect; the same
  request with a NEW request_id after the boundary is a new request decided against current authority (PROT-H23 R5).

## 5. Revocation (`Deployment.revoke`)

Caller must be the issuer of the edge or the issuer of any edge on its path (an upstream issuer can cut downstream).
Else DENIED `not_revoker`. Unknown edge -> INVALID `unknown_edge`. Already revoked -> OK {"already": true}, no mark.
Revoking an edge invalidates every edge below it (validity is recursive, section 3b); no per-descendant write is needed.
There is no un-revoke; a new edge with a new id is required.

## 6. Requirements

| Id | Requirement |
|---|---|
| R24-1 attenuation | No committed edge is broader than its parent (section 2.5); no effect commits outside the intersection of every scope on its path. |
| R24-2 freshness | No effect commits through a path that is revoked, expired or whose root lost base authority at its commit point. |
| R24-3 linearizable boundary | Commit order in world_log is consistent with real-time precedence for revoke, delegate, set_authority and effect calls. |
| R24-4 explicit conflict | Cycles, unknown parents, static-delegate mixing, depth overflow and wrong on_behalf_of fail with the named reason and zero change; nothing is granted by fallback (e.g. to base authority when obo names a root). |
| R24-5 durability | Edges and revocations survive crash/restart; an after_commit crash of revoke leaves the edge revoked. |
| R24-6 historical authority | `authority_used(request_id)` returns the authority version, commit seq, tick and the path the variant relied on; that path must have been VALID at that seq. The historical answer never re-legitimises the path now (a new request through it is decided now). |
| R24-7 safe progress | Every request the oracle allows in EVERY linearization consistent with real time commits (OK). UNAVAILABLE/DENIED on such a request is progress loss. Global blocking on revocation is not safety. |

## 7. Mutants (constructor names; frozen in r3_shared.mutants.KNOWN["H24"])

- `non_attenuating_delegation`: issuance skips the subset/expiry checks AND use evaluates only the last edge's scope.
- `stale_authority_cache`: authority decisions/paths are cached per (subject, obo, op, resources) and the cache is not
  invalidated by revoke/set_authority/expiry (cache lives where a real decision cache would).
- `revoke_commit_reorder`: revoke returns OK and applies the revocation (and its mark) after the next effect commit
  (acknowledge-then-apply).
- `expiry_inclusive`: an edge is usable at tick == expires_at.

## 8. Safe-progress measurement (anti-masquerade)

Reported in safe-progress.json per variant: (i) unaffected-legit progress = OK / requests legal in every consistent
linearization (target 1.0, R24-7); (ii) race overlap = fraction of race cases whose two calls overlapped in real time
(harness record); (iii) order split = among overlapping revoke/execute races, count with effect-first vs revoke-first
order. FROZEN progress floors (author decision 2026-10-07 #2b): (i) must be 1.0; (ii) >= 0.50; (iii) at least 1 effect-first
order. Any floor unmet -> the variant cannot be SUPPORTED (INCONCLUSIVE). Zero forbidden effects with (i) < 1.0 is not evidence of the claim.

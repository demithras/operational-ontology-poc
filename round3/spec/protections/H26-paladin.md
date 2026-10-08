# H26 protections - Paladin variant (protection spec: spec/protections/PROT-H26.md)

Where each H26 requirement and mutant lives (`file:line`). Lines refer to the commit tagged `r3-g3-paladin`. Shape ("Paladin-shaped"):
the disclosure rules of the v3 authority document are interpreted by ONE visibility function, `low_view`
(src/paladin/sovview.py:50), a least fixpoint over public types, non-via rules, own/act-implies-exists objects and via-rules; EVERY low channel
answers only from that value, so hidden and absent share one code path (`view.objects.get(ref) is None`). Sovereignty is implemented here
(author decision 2: nothing shared with the conventional variant or the oracle). Authority is decided before existence: the Engine's authority decision is
evaluated over the DECLARED resources of the request with an EMPTY world (src/paladin/core_g3.py:96), inside the effect transaction, before the Engine
pipeline reads any object. No vendored Engine/Toolchain file changed.

## Requirements R26-1 .. R26-7

| Id | Where it lives | Mechanism |
|---|---|---|
| R26-1 noninterference | src/paladin/sovview.py:50, src/paladin/sovchan.py:23, src/paladin/public.py:29, tests/paladin/test_pal_g3_h26_pairs.py | Every output is a function of (low view, authority, request ids): reads, lists, links, queries, tools, events, provenance views, and the public form of every mutating response. Paired worlds differing in a protected fact (F, E, L, D, G variations) give byte-identical batteries of ~190 observations. |
| R26-2 nonexistence | src/paladin/sovchan.py:66, src/paladin/sovchan.py:80, src/paladin/capgraph.py `edge_visible`/`check_issue`/`check_revoke`, src/paladin/core_g3.py:175, src/paladin/sovprov.py:18 | not_found / unknown_parent / unknown_edge / unknown_case / unknown_decision are the answers for hidden and absent alike; no 403-vs-404 split anywhere. |
| R26-3 no value exfiltration | src/paladin/public.py:16, src/paladin/sovchan.py:89 | Refusal bodies are `{"reason": <constant>}` (gate class or PROT-H23/H24/H25 code); no exception text, values or counts; queries run over the low view with constant error answers. Canary scans in the pair tests (CANARY strings) over every response. |
| R26-4 surface | src/paladin/sovchan.py:121, src/paladin/deployment.py:156 | Descriptors use `r3_shared.disclosure.tool_schema` verbatim; names = the generated capability-aware surface plus the operations of live edges (root must hold the op) and active emergencies the subject is a grantee of (PROT-H26 3.4 wording); equals `allowed_operations` for every fixture principal (test_tools_are_exactly...). |
| R26-5 truthful redaction | src/paladin/sovprov.py:119, src/paladin/sovprov.py:98, src/paladin/sovprov.py:152 | Fields are the TRUE value or `{"redacted": kind}` (actor / args / digest / edge); `partial` is constant true; chain fields are never returned; authority_version is always redacted; hidden edges in a path are replaced in order by the edge marker. |
| R26-6 write safety unchanged | src/paladin/core.py:220, src/paladin/core.py:330 | Frozen order token -> schema -> authority -> existence/preconditions/rules/approvals on every mutating call (call_tool, direct, approve, delegate, revoke, constitutional). H23/H24/H27 suites stay green; the three tests that encoded the old "existence before authority" freedom were updated (see below). |
| R26-7 progress (measured) | tests/paladin/test_pal_g3_h26_surface.py | read correctness and exposure are exact on the fixtures; over-redaction is bounded by the lowness rules below. |

## Frozen check order and public forms
`Core.run` (src/paladin/core.py:210): op known -> request shape -> E-9 schema -> principal/delegation -> (in the effect transaction) edge path -> authority over declared
resources -> `case_required` -> Engine inputs gate (existence) -> preconditions -> policies. `Deployment._pub` (src/paladin/deployment.py:170) maps every non-OK result to
`{"reason": code}` and rewrites execution/effect ids to be derived from the request id (determinism, s5; no counters, uuid, time or id()).
Subscriptions: ids are `sub-<n>` per deployment; `poll` replays the world_log tx by tx over a shadow copy and emits an event for a touched object/link only when
the observer's low projection of it changed (src/paladin/sovchan.py:166). Subscriptions are in memory (lost at a crash, by design).

## Mutants (constructor-activated, frozen names; tests/paladin/test_pal_g3_h26_mutants.py, test_pal_g3_h26_prov.py)

| Mutant | Site | Effect |
|---|---|---|
| existence_status_split | read layer src/paladin/sovchan.py:70; authorization layer src/paladin/core.py:326 | hidden existing object -> DENIED forbidden / authority, absent -> INVALID not found (read and mutating) |
| error_detail_leak | src/paladin/deployment.py:171 (+ `leak_detail` src/paladin/sovchan.py:105) | refusal bodies carry the failing request's object values |
| hidden_tool_schema | src/paladin/sovchan.py:117 | tools() lists every operation |
| provenance_edge_retained | src/paladin/sovprov.py:126 | hidden edge ids and actors returned unredacted |
| subscription_unfiltered | src/paladin/sovchan.py:176 | poll delivers every committed canonical change with raw props |
| redaction_fabrication | src/paladin/sovprov.py:132 | redacted actors become the string "system" without a marker |

## Lowness rules I had to choose (PROT-H26 s4.2 says "the oracle computes this"; stated so the equivalence audit can compare)
- A decision is low iff OWN (observer is subject or on_behalf_of; an approver is the subject of an `approve` decision) or every resource input is existence-visible
  with a covering rule whose provenance is `scalars` or `actors`; subject / on_behalf_of are true only for own or when every input has `actors`.
- `args_digest` is true iff own, or every resource ref in the args is existence-visible and every field a scalar input flows into (ops-spec create/update effects)
  is field-visible. `effect_digest` is true iff every world_log row of the commit is low: object rows (ref visible and written fields visible), link rows (link
  visible), external rows (all input refs visible), the `commit` mark (only if EVERY edge of the authority document it ran under is visible to the observer, because
  the mark carries `authority_version`), `governance` marks (only if the observer sees the case). Refusals have no rows (always true).
- `authority_path` of a decision is the edge marker as a whole if any edge on it is hidden.

## Frozen-text interpretations and gaps (stated, not hidden)
- H-1 `duplicate_edge` (PROT-H24 s2) answers for a caller-chosen edge id that exists but is hidden: ids are caller-chosen, so a colliding id reveals the edge's existence.
  PROT-H26 3.1 lists only parent / revoke / case / decision; left as in PROT-H24.
- H-2 Tools: PROT-H26 3.4 says "(or its delegators/edges/emergencies)"; the Gate-2 test that asserted "an edge holder has no ambient tools" was changed accordingly.
- H-3 Old-order tests changed per Q9: a caller without authority on a NONEXISTENT target is now DENIED (was INVALID): test_h23_r5_r8.py::test_r6_target_existence_and_stale_evidence,
  test_pal_g2_e10.py, test_pal_g2_fix1.py::test_e8_*; test_pal_g2_h24.py (hidden parent -> unknown_parent) and body-shape assertions (`{"reason"}` only, `read()` forms).
- H-4 `query` errors (unknown name, wrong arguments, a function that cannot run over the low view) are constant INVALID answers (`unknown_query`, `invalid_args`, `query_error`).
- H-5 Subscription events carry, for `update`, only the changed/added low fields; a field turning hidden is not announced.
- H-6 Static-scan hits the auditor should expect (all pre-date Gate 3): src/paladin/boot.py:34/53/72 select adapters and bindings by domain name (wiring, no authority decision).

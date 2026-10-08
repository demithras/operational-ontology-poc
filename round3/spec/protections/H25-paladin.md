# H25 protections - Paladin variant (protection spec: spec/protections/PROT-H25.md)

Where each H25 requirement, check and mutant lives in the Paladin variant (`file:line`, one sentence). Lines refer to the commit tagged
`r3-g3-paladin`. Shape ("Paladin-shaped", EQUIVALENCE-G3): the governance document is DATA that is COMPILED once into typed control-plane
relations (`GovIR`: bodies, matters, transitive `superior`, precedence list; src/paladin/govir.py:54) and ONE generic
procedure (`CaseBook`, src/paladin/procedure.py:34) evaluates every model on both domains. Cases, judgments, appeals and
emergencies are commit-ordered FACTS: the record is the `governance` marks in the world_log (src/paladin/core_g3.py:44); the case args and
the request ids behind judgments are kept beside them in the ledger meta and the book is rebuilt from marks + meta at restart
(src/paladin/core_g3.py:57). Emergency authority is one generic Engine authority rule for a reserved role
(src/paladin/authcompile.py: `gov-emergency`) that only the control plane can attach (shadow principals `gov:em:<pid>`, built after the procedural
checks of an `act`; non-delegable). No decision path names a domain, model id, body id or principal id; no per-model code exists.
No vendored Engine/Toolchain file changed in Gate 3 (VENDORED.json unchanged, tests/paladin/test_p2a_vendored.py green).

Entry points: `Deployment.constitutional` -> `Core.constitutional` (src/paladin/core_g3.py:130); `set_governance` ->
`Core.replace_governance` (src/paladin/core_g3.py:307); effects of `execute` / `act` go through the ordinary effect commit
`Core.run` / `Core._commit` with a hook object (`GovExec` / `GovAct`, src/paladin/govhooks.py:40, src/paladin/govhooks.py:68) that runs the
procedural checks INSIDE the world transaction at `tx.tick` and writes the one `governance` mark in the same transaction.

## Requirements R25-1 .. R25-8

| Id | Where it lives | Mechanism |
|---|---|---|
| R25-1 procedural equality | src/paladin/procedure.py:97, src/paladin/procedure.py:134, src/paladin/procedure.py:152, src/paladin/govir.py:87, src/paladin/core_g3.py:181..src/paladin/core_g3.py:298 | The s2 evaluator (competent body by precedence list, eligible judges with requester recusal, single/quorum/concurrence/review stage outcomes, lapse, final outcome, basis) and the s3 actions in the frozen check order; every OK writes exactly one `governance` mark built by `r3_shared.constitutional.governance_mark` (keys/digests/basis order frozen) in the action's own world transaction. |
| R25-2 no effect without legitimacy | src/paladin/core.py:332, src/paladin/govhooks.py:26, src/paladin/core_g3.py:121 | Ordinary call_tool/direct/edge requests of a GOVERNED request are refused DENIED `case_required` inside the effect transaction, before existence; `execute` commits the effect only after `final_gate` (final ALLOW at the commit tick) and a base-authority re-check at that commit. |
| R25-3 no fabricated judgment | src/paladin/procedure.py:70, src/paladin/procedure.py:152, src/paladin/core_g3.py:224 | A judgment exists only as a committed `judge` mark by an eligible member (first per member and stage); `merit` is hashed into the mark and never read by any decision path; an unjudged stage is AWAITING (`oracle_needed`); a decision exists without judgments only through a document-declared lapse (rule `lapse`, basis `[]`). |
| R25-4 bounded emergency | src/paladin/govhooks.py:68, src/paladin/procedure.py:200, src/paladin/core_g3.py:210 | `act` is accepted only for an emergency whose declare case is FINAL ALLOW and not ended, a grantee, a request covered by the emergency scope (`scope_covers`), `tick < expires_at` (strict), no deny grant matching the caller; the Engine then runs as the grantee's shadow principal, which is the ONLY holder of the emergency role. Nothing is granted: expiry/end leave no state behind (the next request is decided from the document and the base authority alone). |
| R25-5 explicit unresolved | src/paladin/govhooks.py:26, src/paladin/core_g3.py:201, src/paladin/core_g3.py:121 | `oracle_needed`, `not_final`, `precedence_unresolved` are explicit refusals with zero world rows (the transaction is rolled back); a governed request never falls back to base authority. |
| R25-6 genericity | src/paladin/govir.py:54, src/paladin/procedure.py:34, `tests/paladin/test_pal_g3_h25_more.py::test_renaming_*` | One compile + one evaluator; ids are opaque keys. Metamorphic renaming of model/body/matter ids changes no status, reason or mark (3 models x project). `DOMAIN_LOGIC_MODULES` is declared in src/paladin/variant.py. |
| R25-7 durability and replay | src/paladin/core_g3.py:57, src/paladin/core_g3.py:154 | Marks are the record; meta is written INSIDE the transaction (undone on in-process failure); `before_commit` fires before any write (rolled back = absent), `after_commit` after the commit; the request_id ledger row is a COMMITTED row written in the same transaction (execute/act use the effect ledger protocol). Same request id returns the stored result; `execute` stores its result per case. |
| R25-8 safe progress | src/paladin/core_g3.py:139 | Decide + commit take the deployment lock and one short world transaction; no refusal depends on an unrelated action (6-thread execute race commits one effect, tests/paladin/test_pal_g3_h25_more.py). |

## Frozen check order (PROT-H25 s3, first failure wins)
3.0 token (`Deployment._constitutional`) -> schema (`check_action`, request_id) -> replay of a committed request id -> `no_governance` (src/paladin/core_g3.py:148).
3.1 propose (src/paladin/core_g3.py:181): duplicate_case, schema (E-9, also for `emergency:declare` with its pseudo-operation schema), not_governed,
matter_conflict, no_authority (`base_denied`: delegation / edge path at the commit tick / Engine authority over DECLARED resources), precedence_unresolved,
then the declare extras (scope_amplification, emergency_too_long, not_grantee). 3.2 judge (src/paladin/core_g3.py:224): unknown_case (includes
"cannot see the case", `CaseBook.seers`), not_eligible, stage_closed, already_judged. 3.3 appeal: unknown_case, not_reviewable, not_decided, not_party,
already_appealed, window_closed. 3.4 execute (src/paladin/core_g3.py:276, src/paladin/govhooks.py:40): unknown_case, not_requester, stored result,
oracle_needed, not_final, case_denied, no_authority, then the operation's own pipeline. 3.5 act (src/paladin/govhooks.py:68): emergency_inactive, not_grantee,
out_of_emergency_scope, emergency_expired, no_authority (deny grant), then the operation's schema and pipeline. 3.6 `set_governance` validates with
`validate_governance` and replaces the document; open cases are re-evaluated from that commit on (no grandfathering, Q14: `CaseBook.apply_governance`).

## Mutants (constructor-activated, frozen names; each demonstrably changes behaviour in tests/paladin/test_pal_g3_h25_mutants.py)

| Mutant | Site | Effect |
|---|---|---|
| precedence_inverted | src/paladin/govir.py:95 | each precedence criterion keeps the MINIMAL elements: the wrong body decides |
| quorum_weakened | src/paladin/procedure.py:88 | a quorum body allows at k-1 concurrences |
| emergency_no_expiry | src/paladin/govhooks.py:84 | `act` ignores expires_at (end still works) |
| merit_autofill | src/paladin/govhooks.py:29 | an AWAITING stage at execute is treated as ALLOW with an empty synthesized basis, at the place the final outcome is computed |
| domain_privilege_branch | src/paladin/core_g3.py:125 | the decision path skips `case_required` when the domain is "project" and the requester id ends in "-1" (must be killed by the A5 audit: static scan hits src/paladin/core_g3.py on the string literals; metamorphic renaming of principal ids flips the outcome) |

## Frozen-text interpretations and gaps (stated, not hidden)
- G-1 Lapse (s2.5 "fixed at that transaction"): a due lapse is fixed at the FIRST successful constitutional/effect transaction whose tick >= propose_tick + after
  (`CaseBook.settle`, applied before the event); a refusal evaluated earlier sees the lapse lazily with its OWN tick as `decided_tick` (so a lapsed case whose
  matter has a review window reads `not_final` until some transaction fixes it). The text does not say which transactions count; the oracle may differ.
- G-2 `end` refusals are not specified: unknown / ended / not-ACTIVE emergency -> DENIED `emergency_inactive`; caller not a member of a declaring body -> DENIED `not_eligible`.
- G-3 `execute` of an `emergency:declare` case has no operation to run: after the s3.4 checks it commits an `execute` mark and returns OK {"case"}.
- G-4 `set_governance` re-evaluation: a stage that is decided under the new document and was not decided (or decided differently) before is decided AT the set_governance
  commit (seq/tick); a stage no longer decided becomes AWAITING again. The text says only "re-evaluated under the new document from that point on".
- G-5 `emergency:declare` base authority uses the static upper bound `allowed_operations` (an allow grant whose operation pattern matches, deny on the principal or a
  delegator wins). The v1/v2/v3 fixtures grant it to nobody but admin (`*`); harness generators must add an `emergency:*` grant to declare as another principal.
- G-6 Several covering matters with different reviewers/lapse: the governing matter is the first remaining (body, matter) pair in document order (concurrence: the first
  covering matter).

# H28 protections - Paladin variant (protection spec: spec/protections/PROT-H28.md; protocol: spec/gate4/PROTOCOL-P1f.md)

Mechanism in one paragraph. Governance stays where it was: the Engine pipeline (gates -> approval -> constraints) decides inside the
request's single world transaction. In external mode (`deploy(external=ExternalBinding)`) the Engine's external-call adapters are
`worldbridge.OutboxAdapter`s: they only PLAN the effect (system, ops-spec operation, payload) and report no observation. After the
world commit the Core makes the intent durable (`extdispatch.ExtPlane.register`: I, the per-effect cap, the outcome record PENDING) in
the request ledger's meta store (`led/meta/ext/...` in a HistoryStore), then returns the unchanged decision with `outcomes`. Adapters
are called only from `dispatch_pending` (cap + byte-exact decision envelope). Outcome truth comes only from `reconcile`, which reads the
ObservationClient and applies Paladin's own P1f-6 function (`extoutcome.outcome_state`). `external=None` keeps the legacy path.

| Requirement | Mechanism (file:line, src/paladin/) | Tests (tests/paladin/) |
|---|---|---|
| R28-1 decide before dispatch | `core.py` `_commit` (commit, then `ext.register` at :362); adapters called only in `extdispatch.py` `dispatch` :71 / `_submit` :85 from `deployment.py` `dispatch_pending`; replay returns the stored body | test_pal_g4_decision (twin differential x6 adapters, world log identical), test_pal_g4_seam |
| R28-2 no adapter-minted authority | `extdispatch._submit` reads only `reply.status` (AST-checked: no `.body` read, no authority vocabulary); reply status is stored, never the body; `OutboxAdapter.observations() == []` | test_pal_g4_decision (PolicyReply, refusal-as-outcome), test_pal_g4_static |
| R28-3 generic enforcement | rules stay in the IR policies/ops-spec `RuleSet` (`boot.py` :41 / `extops.py`); no rule in ADAPTER_MODULES | test_pal_g4_decision `r28_3`, test_pal_g4_project, test_pal_g4_static |
| R28-4 vocabulary | `extoutcome.py` + `extdispatch.public` form validated by `r3_shared.outcome.validate_outcomes` | test_pal_g4_outcome (`one`), test_pal_g4_outcome_fn |
| R28-5 outcome function | `extoutcome.outcome_state` (rules N,U,D1,D2,D3,S,F,W), Paladin's own code; adapter reply is not an argument | test_pal_g4_outcome_fn (19 rows, coverage set difference, precedence) |
| R28-6 monotone safety | success needs a corroborating observer row (rule S); RECONCILED_* -> DIVERGED only along growing views | test_pal_g4_outcome (L1 pending then failed, DIVERGED absorbing), test_pal_g4_outcome_fn |
| R28-7 duplicates | cap `max_uses` (1 / 1 / 3 by class) + ExternalWorld; never a second cap | test_pal_g4_retry, test_pal_g4_property |
| R28-8 retry / redelivery | `extdispatch.due` (<= 3 submissions, same cap, never after SUCCESS/DIVERGED/OK reply); intent durable before dispatch, restart() resubmits | test_pal_g4_retry (timeout-after-apply, omission, crash after commit, replay) |
| R28-9 observation path | `extdispatch.reconcile` reads `binding.observer` only; no `observations()` of an action adapter is read in external mode | test_pal_g4_outcome, test_pal_g4_seam |
| R28-10 observability classes | `extoutcome` rule N (`none` -> UNKNOWN/low always); effects_only -> confidence low; observer faults -> rule U / withheld rows | test_pal_g4_outcome (effects_only, unavailable, lagging), test_pal_g4_outcome_fn |
| R28-11/12 governance in adapter | behaviour: twin test above; static: ADAPTER_MODULES = worldbridge, extdispatch, extoutcome, extoutbox (clean) | test_pal_g4_static, test_pal_g4_mutants |
| R28-13 attenuation | `extdispatch.attenuate` :31: system, operation, target, payload_digest, correlation `rid#i`, max_uses, not_after_tick = commit tick + window | test_pal_g4_seam (every system, caveats exact, never root) |
| R28-14 effect outside scope | the only widening path is the mutant `credential_scope_broadened` | test_pal_g4_mutants |

Project domain (Q2): the H28 overlay operations are compiled into IR actions + generic bindings from the ops-spec data by
`extops.py` (inputs, preconditions, deny / require_approval business rules, external effect); no operation or rule name appears in
src. Vendored patch `G4a` (domains/project/logic/constraints.py): the two Round 2 hard constraints skip `external_call` entries
(documented in H23-paladin.md, recorded in VENDORED.json).

## Declarations (P1f-8)
`variant.ADAPTER_MODULES = (paladin.worldbridge, paladin.extdispatch, paladin.extoutcome, paladin.extoutbox)`,
`EXTERNAL_HISTORY_PREFIXES = ("led/meta/ext/",)`. `PaladinVariant.adapter_modules` (instance property) adds `paladin.extgate_mut` for the
`policy_gate_in_adapter` build only (a mutant-only module loaded by name; absent from a clean build's import closure).

## Mutants (P1f-9), each at its real site
| Mutant | Site | Killed by (own class) |
|---|---|---|
| adapter_success_trusted | `extdispatch.py` :118 (reconcile believes reply OK) | false_reconciled_success on L1 |
| credential_scope_broadened | `extdispatch.py` :36 (cap without target + payload digest) | effect_outside_scope on T1-style writers |
| policy_gate_in_adapter | `boot.py` :82 (gating rules leave the decision plane via `extgate_mut.strip`) + `extgate_mut.refuses` (adapter-side rule) | oracle_denied_variant_ok + static hit (opsrules import, rule-id literal) |
| idempotency_disabled | `extdispatch.py` :38/:89 (fresh chain + unbounded uses per submission) | duplicate_effect on L2/L3 |
| observation_coupled | `extdispatch.py` :102 (snapshot synthesised from adapter replies) | false_reconciled_success on L1 |
| divergence_rewritten | `extoutcome.py` :46/:51 (D2/D3 skipped) | target_mutation_detected < 1.0 |

## Decisions recorded where the frozen text is silent or contradictory (see the build report)
1. Evidence form: G4-E6 (namespaced strings) vs schemas/external-outcome.schema.json + `validate_outcome` (integers): integers are emitted
   (the sorted union of used effect/audit seqs); equality never compares evidence.
2. Frozen P1f-6 read literally lets SUCCESS fall back to PENDING when a LATER read withholds rows (larger lag, smaller watermark); the
   function is implemented literally, not guarded (documented test `negative_literal_function_regresses_on_a_withdrawn_view`).
3. GEN-NULL requests cannot arise from the ops specs; only rule N is implemented for such a system (pure-function tests).
4. Engine execution state in the OK body (`state`) is `OUTCOME_UNKNOWN` in external mode (no Engine-visible observation); the P1f
   outcome records are the only outcome truth.

# Gate 4 equivalence (H28): Paladin mechanism vs strongest conventional equivalent

DRAFT (g4-design 2026-10-09). DUAL_TRACK: same seam (ExternalBinding), same ExternalWorld + observer trust class, same
corpus/oracle/evaluator. Shared code is limited to P1f (forms, caps crypto, ExternalWorld, ObservationClient, outcome
vocabulary). Each variant implements its own dispatch, attenuation choice, retry policy and outcome function.

| PROT-H28 item | Paladin mechanism (expected) | Strongest conventional equivalent | Fairness risk / audit point |
|---|---|---|---|
| R28-1 decide before dispatch | Engine pipeline: gates -> EFFECTS_COMMITTED journaled -> adapter dispatch from the Engine's effect stage; envelope rendered by provenance.py | Service: authorize (PDP) -> transactional outbox row in the same world commit -> dispatcher worker submits | Paladin today dispatches INSIDE the world tx (worldbridge); conventional inline in effects.apply. Both must move to outbox; auditor checks no reply is read before CallResult status is fixed |
| R28-2 no adapter-minted authority | Adapters never see gates (Engine H20 rule); reply stored as `responses` only; authority code never reads responses | Reply object typed `AdapterReply`, stored in an outcome table never joined by PDP/approval code | Paladin `gates.make_ctx(..., responses=rec["responses"])` passes adapter replies into the OUTCOME predicate context - today a predicate may read them (adapter_success_trusted risk) and they must reach no gate/policy binding (audit + C28-2) |
| R28-3 generic enforcement | Deny rules/approvals in IR gates | Deny rules/approvals in PDP over ops-spec data (G3 ruling Q1 data-not-code) | Same static audit + same twin/oracle differential for both |
| R28-5 outcome function | Outcome predicate per action rewritten to read ONLY observer-derived observation types (new ObserverAdapter producing IR observations from ObsSnapshot); states extended with PENDING/DIVERGED (pipeline TRANSITIONS change) | Reconciliation job: state machine table keyed (request_id, effect_index) implementing P1f-6 directly | Paladin's IR-level predicate is domain-authored (manufacturing/logic/actions.py); conventional's is one generic function. Risk that Paladin per-action predicates diverge from P1f-6 for one action -> C28-2 per action |
| R28-6 monotone safety | Engine journal + TRANSITIONS table (RECONCILED_* -> DIVERGED only) | DB CHECK on allowed transitions | none beyond C28-2 |
| R28-7/8 idempotency | Engine idempotency key `<request_id>~<attempt>`: attempts must reuse ONE cap per effect (cap stored in the journal) | Idempotency-Key + stored per-effect token in the outbox row; retries reuse it (Stripe-style) | Paladin attempt suffix currently feeds `request_id_of`; must not create a new correlation per attempt |
| R28-9 observation path | ObserverAdapter registered separately from action adapters; `observations()` of action adapters removed/ignored | Reconciler reads ObservationClient only | Paladin worldbridge fabricates observations today (observation_coupled is its CURRENT behaviour) - largest rework; give conventional no head start: both builders get PROT-H28 only |
| R28-10 stop rule | IR observation type absent for `none` systems -> predicate None -> UNKNOWN low | Config-driven: observability from systems.json | Both read observability from systems.json (data); hard-coding per system name = static hit |
| R28-11/12 governance audit | ADAPTER_MODULES: worldbridge, engine.effects (adapter part), engine.outcome, new observer adapter | ADAPTER_MODULES: effects (external part), outbox dispatcher, reconciler | Same scanner, same resolution rules, reviewed by the same auditor before freeze |
| R28-13 attenuation | Capability-graph idea extended: Engine derives per-effect cap in the WriteGrant step | Token exchange (RFC 8693-style) in the dispatcher: per-request downscoped token | Both use extcap.attenuate; difference is WHERE it happens. Conventional must not be given a coarser per-system service token "because that is typical" - DUAL_TRACK requires the strongest equivalent (least-privilege per request) |
| crash after commit | Engine recover(): EXECUTING without response -> OUTCOME_UNKNOWN, never re-calls adapter | Outbox redelivery with the same token | Behaviour differs legitimately: Paladin never resubmits (state UNKNOWN until observer decides), conventional resubmits. Both are allowed by R28-8; P1f-6 treats observer truth the same. Progress floor (PROT s8) is computed on honest cases WITHOUT a crash point only, so the two legitimate recovery styles are not scored against each other; crash cases are judged on duplicate_effect and outcome equality only |

## Fairness risks to rule on before freeze
F1 Paladin's `OUTCOME_UNKNOWN` (engine) vs P1f `UNKNOWN`/`PENDING`: the public outcome form must map exactly; the
   mapping is variant code, audited, not a harness translation (harness never relabels variant states).
F2 Paladin domain predicates (actions.py) vs conventional generic reconciler: if Paladin keeps per-action predicates,
   they must be DATA-equivalent to P1f-6 or they are a liability measured honestly; no harness exemption.
F3 Inline vs dispatch_pending: both may dispatch inline; the harness always calls dispatch_pending at the same points
   for both (equal schedules); a variant that dispatches inline answers {"submitted": 0}.
F4 Latency: ExternalWorld socket round-trips dominate; p95 descriptive only.
F5 The conventional builder receives PROT-H28 + P1f only, never Paladin source (DUAL_TRACK); the equivalence auditor
   reviews both seams against this table before dev1 and records rows in HARDENING_LEDGER.jsonl.

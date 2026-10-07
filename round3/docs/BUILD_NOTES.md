# Round 3 build notes

Running notes for the dual-track build (paladin vs conventional). Each phase appends a section.

## P1 - variant-neutral foundation (tag r3-p1-foundation)

### Module map (`round3/src/r3_shared/`)
| Module | Purpose |
|---|---|
| `clock.py` | `LogicalClock` (integer ticks, `advance(n)`); no wall clock anywhere in decision paths |
| `identity.py` | `IdentityProvider(secret).issue(sub, aud, ttl, clock)`, `TokenVerifier.verify/claims` (HMAC-SHA256, claims sub/iat/exp/aud/jti, raises `TokenError`) |
| `world.py` | Ground truth: `WorldStore(path)` -> `handle(writer)` (`WorldHandle`: create/update/delete/link/unlink/external_write + reads, `transaction()`), `reader()` (`WorldReader`, SQLite `mode=ro`, `snapshot()`), `diff(before, after)` |
| `opsspec.py` | Load/validate `spec/ops/<domain>.json`; `World` + `evaluate()` for the simple predicate subset |
| `authspec.py` | Load/validate `spec/authority/<domain>.json`; `allowed_operations()` static upper bound (deny overrides, delegation = delegable grant AND delegator allowed) |
| `variant.py` | `Variant`, `Deployment` protocols, `ToolDescriptor`, `CallResult` (status OK/DENIED/INVALID/UNAVAILABLE/UNKNOWN) |
| `registry.py` | `VARIANTS` (lazy `load_variant`; missing implementation -> `NotImplementedError("... not implemented yet")`) |
| `evidence.py` | Envelope builder/validator/writer (schema `schemas/evidence-envelope.schema.json`, freeze hash from `protocol/FREEZE.json`, `payload_sha256`) |
| `verdict.py` | `Verdict`, `evaluate_common` (copy of round2 `hdd/verdict.py`, strict: only literal `True` counts), `evaluate_from_mapping`, `DualVerdict` |

Generated, committed: `spec/ops/{manufacturing,project}.json`, `spec/authority/{manufacturing,project}.json`
(generator `scripts/build_ops_spec.py` + `scripts/specgen/*`; `--check` regenerates and diffs). Schemas: `schemas/ops-spec.schema.json`, `schemas/authority-spec.schema.json`.
Tests: `tests/` (`fakes/fake_variant.py` is test-only and never registered).

### Design decisions
- World canonical keys are `"Type:key"` strings in `canonical_links`; effect records from `diff` are `create/update/delete/link/unlink/external`.
- Writers: variants write through `handle("paladin-service" | "conventional-service")`, adapters through `handle("WMS" | "ERP" | "MES")` (see `service_accounts[].world_writers` in the authority fixture). The oracle can reject effects from any other writer.
- Ops spec describes WHAT: typed inputs, declarative `preconditions`, `business_rules` (deny / require_approval / classify), `effects` (canonical writes or external adapter calls), `gated_inputs` (= `immutable_after_authorization`: once a request is authorized, changing any of these needs a fresh decision), approval requirements, expected outcome. Complex helper reads (e.g. `protecting_work_orders`) are defined in prose under `helpers`; the AST evaluator raises `Unevaluable` for them.
- Time: 1 tick = 1 second. Round 2's `EvidenceSnapshot.snapshotObservedAt` (ISO datetime) is an integer tick in the neutral seed (freshness window 5 ticks).
- Project domain: Round 2 effects were Git changes; the neutral spec treats them as canonical world writes. Round 2's evaluator (registered code reading git blobs) is replaced by an explicit neutral evaluator `neutral:evidence-present-v1`; `compute_freeze_hash` is a neutral canonical-JSON hash (not byte-identical to Round 2). The project seed is synthetic (51 objects), not read from git.
- Excluded as control-plane (not neutral workload): manufacturing `Decision/ActionExecution/Outcome/AuthorizationCheck/...` types, function `decision_content_hash` (listed under `unsupported`; H27 territory). Both variants exclude them.
- **FINDING carried from Round 2**: the frozen manufacturing IR names rules for the wrong capability, so `expedite_purchase_order` and `reschedule_work_order` cannot pass authority there (`round2/tests/domains/test_manufacturing_logic.py`). The neutral authority fixture adds `origin: neutral-fix` grants (planner may expedite/reschedule; supervisor approves them), mirroring that test's patched IR. The Paladin builder must patch its IR identically; orchestrator may instead move these two operations to `unsupported` for both variants.
- Grants carry `origin` (`round2` | `neutral-fix` | `neutral-extension`) so every deviation from Round 2 is auditable. Agents: manufacturing `agent-1` (delegated by planner-1, all warehouses), `agent-hostile-1` (WH-B/WH-C only), `agent-orphan` (delegator holds nothing); project `agent-evidence-1` (hostile; start_run, attach_evidence), `agent-draft-1`. Admin = `admin-1` with `*`.
- Project delegation: every Round 2 grant is `delegation_allowed=false`; `delegations` is empty so any `on_behalf_of` call must be denied.
- Read policy is not specified yet (any authenticated principal may read); H26 refines it.

### What P2 / P3 need
- P2 (variants): consume `ops_spec`/`auth_spec` dicts passed to `Variant.deploy`; write only through the supplied `WorldHandle` factory; implement `tools/call_tool/direct/read`, return `CallResult`; Paladin must build IR/pack from the neutral spec only where it chooses to, but may not edit the spec. Seed the world from `ops_spec["seed"]` (helper for seeding is intentionally left to the harness).
- P3 (oracles/harness): read specs via `load_ops_spec/load_auth_spec`; measure effects with `WorldReader.snapshot()` + `diff`; never trust `CallResult`; use `evaluate_common`/`DualVerdict` and `evidence.write_envelope`.
- Not provided in P1 (by design): world seeding helper, oracle logic, token issuing policy for principals (harness issues tokens with `IdentityProvider`; audience convention left to the harness/variants, fake uses "fake").

## P3 - H23 harness (tag r3-p3-h23-harness)

Variant-neutral: oracle, effect meter, adversarial state machine/corpus, mutation proof, evaluator. Built and tested only
against fakes (`tests/fakes/h23_fakes.py`: correct / allow-all / direct-open / deny-all; never registered).

### Module map
| Path | Purpose |
|---|---|
| `r3_oracle/authority.py` | `decide(subject, on_behalf_of, op, resources, auth_spec)` = frozen effective-authority rule (PROT-H23); `could_ever_allow` (surface upper bound), `revoke`, `approver_ok` |
| `r3_oracle/expr.py`, `view.py` | independent evaluator of the ops-spec predicate AST (all node kinds of both domains), read-only snapshot view |
| `r3_oracle/helpers.py`, `helpers_project.py` | every prose helper/read of both domains, one function each, implemented from the spec text |
| `r3_oracle/ops_model.py` | `evaluate(...) -> Outcome(kind, effects)`: COMMIT / DENIED_AUTHORITY / DENIED_RULE / INVALID / NEEDS_APPROVAL / UNKNOWN_OP + exact expected effect records; `match_records` |
| `r3_oracle/effect_meter.py` | per-call WorldReader diff; AST test forbids reading CallResult |
| `r3_shared/mutants.py` | the four H23 switches (`is_on/enabled/CONSULTED`); created here because P1 did not provide it (merge note: P2 builders consult `mutants.is_on(name)`) |
| `r3_harness/h23/` | `env` (deployment + measured call), `rules` (10 attack rules), `corpus` (seeded driver, coverage sequences), `machine` (hypothesis RuleBasedStateMachine), `classify`, `surface`, `mutation`, `analyze`, `runner`, `evaluator` |
| `scripts/run_h23.py`, `evaluate_h23.py`, `verify_h23.sh` | run / evaluate / re-hash + re-evaluate + diff |

### How to run
```
cd round3 && .venv/bin/python scripts/run_h23.py --exp-id exp-h23-001 --variants paladin,conventional --seed 1 --sequences 10000
.venv/bin/python scripts/evaluate_h23.py exp-h23-001 && scripts/verify_h23.sh exp-h23-001
# dev with fakes (only with --test-variants): --variants fake-correct,fake-allow-all --sequences 200
```
Output: `experiments/h23/<ID>/<variant>/{adversarial-sequences.jsonl, effect-oracle-diff.json, identity-confusion-results.json,
direct-engine-backstop.json, mutation-results.json, surface-audit.json, envelope.json}` and `<ID>/verdict.json`.
The evaluator recomputes everything from the raw jsonl; summaries are only cross-checked (mismatch -> INVALID).

### Semantics fixed by the harness (document for the orchestrator)
- Per sequence: fresh world store + fresh Deployment, one attacker agent identity, 3-8 rule steps; plus deterministic
  `coverage` sequences (every principal x every operation x both surfaces). Unique = distinct sha256 of (domain, attacker,
  concrete steps); the driver keeps generating until `--sequences` unique ones exist (cap 3x).
- Token audience is detected: `deployment.audience` / `variant.audience` if present, else the first candidate
  (`variant.name`, domain, r3, paladin, conventional, ...) for which `tools(admin token)` is non-empty.
- Authority changes use `deployment.set_authority(auth_spec)` if present; on TypeError/NotImplementedError or absence the
  harness redeploys a new Deployment over the SAME world with the reduced authority (loses variant-side idempotency memory;
  the replay-after-revocation expectation, "decided against the authority in force now", holds either way).
- Effects: only what the diff shows. Expected = oracle effect records (exact multiset). Unexpected record, wrong external
  writer (not in `service_accounts[].world_writers`) or a partial commit -> `forbidden_effect`. `identity_expansion` = forbidden
  effect on a call tagged identity/obo/token. `backstop_failure` = `direct` committed something the oracle denies, or a
  call_tool-denial probe (same call re-sent on `direct`, fresh request_id) did not end as zero-effect AND status != OK.
  `legit_progress_miss` = clean call the oracle allows whose effects are absent. NEEDS_APPROVAL expects ZERO effects
  (no approval channel exists in the Variant protocol, so approved commits are not exercised).
- Business-rule actor (`actor_holds`) = the delegator when `on_behalf_of` is given, else the subject. Agents acting as themselves
  hold only `agent_grant`, so a protected-route transfer by an agent without obo is DENIED_RULE.
- Frozen rule vs fixture note: `agent-orphan` (delegator holds nothing) is ALLOWED when acting as itself, because the frozen rule
  evaluates the subject's own grants (agent_grant on all warehouses). `authspec.allowed_operations` (P1) is stricter; the oracle
  follows PROT-H23.
- Loosely compared props (prose fixes inputs, not text): `Verdict.reason`, `Verdict.derivation_hash` (non-blank / 64-hex).
- TOCTOU attack: `FlipDict` returns benign values on the first read of each key, hostile values afterwards; judged against the
  BENIGN request (R4). Correct variants copy args once at entry.
- Mutation proof: sub-corpus of `--mutation-sequences` (150) per mutant, targeted rule mix, switch OFF vs ON with the same seed;
  killed iff expected classes increase AND the switch was consulted; first counterexample shrunk by step deletion.
- Reads: `Variant.read` is not attacked (H26 territory). `recommend_transfer_for_work_order` / `resolve_canonical_id`
  reads are not needed by any operation and are not implemented in the oracle.

### Runtime estimate (fakes; real variants add their own per-call cost)
~21 s per 1,000 unique sequences incl. mutation proof (150 x 4 x 2) and surface audit; ~28 s per 3,000 sequences without the
mutation proof (~9 ms/sequence, ~1 ms/call, ~9 calls/sequence incl. backstop probes). 10,000 sequences ~ 2-3 min per variant on fakes.
### P3 rework (harness on protocol P1b)
- Mutants: only `registry.load_variant(name, mutants=[m])` (fakes: `FakeVariant(mode, [m])`). `run_variant(factory, ...)` takes
  `factory(mutants) -> Variant`; baseline = `factory(())`. No module-global switch; the `consulted` field is gone: a mutant whose
  site is never consulted gains nothing and is SURVIVED (tested with a variant that accepts but ignores mutants).
- Authority changes: only `Deployment.set_authority`; the redeploy fallback is deleted (a variant whose `set_authority`
  raises fails the run). Each attack sequence logs `authority_version: {initial, final, changes:[{before, after}]}`.
- Audience: `type(variant).audience` (class attribute); missing -> `RuntimeError` naming the variant. No auto-detection.
- Delegate semantics in `r3_oracle/authority.py` (PROT-H23): delegates are evaluated with their delegator on every request;
  obo != delegated_by or obo with `delegated_by: null` -> DENY; `actor_for_rules` = delegator; `could_ever_allow` for a delegate
  also needs a delegation entry and a delegator that could be allowed (agent-orphan no longer exposes transfer_inventory).
- Approvals: `r3_oracle/approvals.py` (valid iff token verifies, op has an `approval` block, approver != requester and outside its
  chain, approver holds `approval.approver_operation` on the resources; key = requester+obo+op+canonical args; single use, consumed
  in `Env.call` when the oracle commits with `used_approval`). `ops_model.evaluate(..., approved=)`; no approval ->
  NEEDS_APPROVAL (`approval_required`), zero effects. Approvals change nothing in the canonical world (any diff = forbidden effect).
  Rules in `h23/approval_rules.py`: appr_ok (approve+commit positive control, then reuse), appr_missing, appr_self, appr_chain
  (chain member legitimately granted the approval op via set_authority, still refused), appr_unauth, appr_forged, appr_swap
  (approve A, commit B), appr_by_attacker (hostile agent as approver with its own token). Honest counterparties (approvers, the
  honest requester of appr_by_attacker) use harness-issued tokens. Only manufacturing has approval operations
  (transfer_inventory, expedite_purchase_order, reschedule_work_order); in project the rules degrade to a legit step.
- Evidence: `approval-results.json` per variant (counts per approval rule); recorded and hashed in the envelope, NOT required by the evaluator.
- Runtime on fakes (fake-correct, seed 2, incl. mutation proof of 150x4x2 and surface audit): 1,000 unique sequences = 22.1 s (8,586 calls); 200 sequences = 14 s.


## P2b Conventional (tag r3-p2b-conventional, branch r3-conv)

Builder worked only from neutral inputs (ops/authority specs, PROT-H23, FAIRNESS, DUAL_TRACK, `r3_shared`); no round2 or paladin source read.

### Module map (`round3/src/conventional/`)
| Module | Purpose |
|---|---|
| `codegen.py` -> `models_gen.py` | typed frozen request model per operation, generated from `spec/ops/*.json`; `python -m conventional.codegen [--check]` |
| `validation.py` | strict schema checks (unknown fields rejected, bool is not int, JSON deep copy, single read of caller keys) |
| `policy.py` | policy decision point (ABAC/ReBAC over the authority spec; deny overrides; on-behalf-of; approver independence; static exposure) |
| `worldview.py`, `interp.py`, `helpers_mfg.py`, `helpers_proj.py` | commit-time interpretation of preconditions/business rules; prose helpers implemented from the spec text |
| `effects.py`, `store.py` | declarative effects applied through `WorldHandle("conventional-service")`; idempotency/approval tables in the world file |
| `service.py`, `tools.py`, `variant.py` | service API (one transaction per request), tool surface, `ConventionalVariant` (audience `conventional`) |
| `mutants.py` | the four H23 switches (names as in PROT-H23; `r3_shared.mutants` does not exist in P1, so they live here) |

Tests: `tests/conventional/` (functional per operation, R1-R8 negatives with zero-effect diffs, mutants, codegen/policy, stateful sequences with known-negative mutant kills). Protection mapping: `spec/protections/H23-conventional.md`.

### Findings / notes for the orchestrator
- `r3_shared.world.WorldHandle` has no auxiliary-table API; `store.py` uses `handle._con` for `conv_idempotency` / `conv_approvals` in the same SQLite file (atomic with effects; invisible to `WorldReader.snapshot`). Suggest a public hook in P1 if Paladin needs the same.
- Spec ambiguity: `exists` over a resource input means the object exists in the world (otherwise `expedite-closed-po` / `reschedule-closed-wo` never fire for absent targets); `exists(new_experiment_id)` tests Experiment existence (helper yields an id).
- `agent-orphan` is allowed without `on_behalf_of` under the frozen rule (see H23-conventional.md); `authspec.allowed_operations` disagrees for delegated principals.
- A `tests/test_variant_protocol.py` P1 test asserted both variants raise NotImplementedError; relaxed to "built or not-implemented" so it holds on both branches.
- Business rules defend in depth: on `PX-17 WH-B->WH-A` the protected-route rule masks a missing authorization check, so mutant tests use an unprotected route (WH-B->WH-C).
## P2a - Paladin variant v0 with H23 protections (tag r3-p2a-paladin)

### Module map (`round3/src/paladin/`)
| Module | Purpose |
|---|---|
| `engine/`, `toolchain/`, `ir/`, `domains/{_support,_hdd,manufacturing,project}` | VENDORED Round 2 code at pin 8f9ff26 (`VENDORED.json`: original/vendored/current sha256 + patch ids; `scripts/paladin_vendor_manifest.py` refreshes it; `tests/paladin/test_p2a_vendored.py` enforces it) |
| `authcompile.py` | neutral `spec/authority/<d>.json` -> Engine `authority_rules`, per-action `authority_refs`, static `Principal`s, delegation table (no domain branches) |
| `worldbridge.py` | Engine State rebuilt from the world per request; `WorldExternalAdapter` (WMS/ERP/MES -> `external_write`), `WorldGitAdapter` (project `git_change` -> canonical writes) |
| `boot.py` | builds one Engine per domain (IR + compiled authority + logic bindings + adapters); `neutral:evidence-present-v1` evaluator |
| `core.py` | identity -> delegation -> shape -> ledger/pending -> Engine pipeline in one world transaction -> `CallResult` mapping; mutant switches live here |
| `surface.py`, `deployment.py` | generated Toolchain surface (`tools`, `call_tool`), `direct`, `read`, `approve`, `set_authority`, `authority_version` |
| `variant.py`, `mutants.py` | `PaladinVariant` (registry: `paladin.variant:PaladinVariant`), H23 switches |

### Conventions the harness must know
- Token audience is `"paladin"` (`paladin.core.AUDIENCE`, also `deployment.audience`). Tokens are issued by the harness with `IdentityProvider.issue(sub, "paladin", ttl, clock)`.
- Deploy on an ALREADY SEEDED world (seeding is the harness's job); the Engine rebuilds its State from the world on every request. The service writer name is `paladin-service`; adapters write as `WMS`/`ERP`/`MES`.
- `tools()` lists operation names (= ops-spec names) of mutating operations only; reads go through `read(token, name, args)` (ops-spec `reads` that are IR functions, plus generic `get {type,key}` / `list {type}`); prose-only helpers are UNKNOWN reads.
- Statuses: DENIED = identity/delegation/authority/approval gate; INVALID = args shape, unknown/identity-like args, missing/reused request id, precondition/policy/constraint refusals; UNAVAILABLE = adapter failure (rolled back); UNKNOWN = unknown operation or a tool absent from the caller's surface. A request that needs approval returns OK with `body.state == "PENDING_APPROVAL"` and ZERO effects; `approve(token, request_id)` (extra, not in the Variant protocol) commits it for a second principal. Replays of a committed request id return OK with `body.replayed == True` and no new effect.
- Mutants: see "P2a rework" (constructor-only, `r3_shared.mutants.validate`).
- `set_authority(auth_spec) -> new version` rebuilds the Engine (its in-memory journal and pending approvals are dropped; the committed-request ledger is kept). `crash()/restart()` raise NotImplementedError (H29).

### Design decisions / ambiguities (flag for the orchestrator)
- PROT-H23 says that without `on_behalf_of` the subject is evaluated "as itself". Paladin follows that literally: the static `delegated_by` of an agent in the auth fixture is NOT applied unless `on_behalf_of` is given (so `agent-orphan` may call `transfer_inventory` as itself via its own `agent_grant`; the shared `authspec.allowed_operations` applies the chain and would say no). Tests use an as-itself bound. If the oracle disagrees, only `Core.principal` changes.
- Business-rule/policy refusals (stale evidence, quarantine, safety stock, protected route, lifecycle) are INVALID, not DENIED (R7: DENIED = authority).
- Delegated requests: `actor_holds` (transfer-protected-route) is true if the subject or any delegator holds the relation (patch D5).
- The spec's `write:*`/`update:*` deny grants are not compiled into Engine rules (they never match an `action:*` capability); they hold structurally (see H23-paladin.md).
- Manufacturing external effects are single atomic adapter writes through each system's own handle (SQLite cannot write from a second connection inside the service transaction); project canonical writes share ONE world transaction, rolled back on any failure.
- ERP/MES observations are synthesised by the adapter from the authorized inputs (ERP reports expectedAt-1; MES reports the requested plannedStart), the same fake-system role Round 2's `ErpFake/MesFake` played; the WORLD effect record is the effect payload.
- Modified a P1 test: `tests/test_variant_protocol.py::test_registry_lazy_and_never_contains_fake` asserted that both variants raise "not implemented yet"; it now accepts a built variant (Variant instance with matching name). The conventional builder will need the identical relaxation.

### Tests (`round3/tests/paladin/`)
`test_p2a_functional.py` (every operation of both domains, reads, approval), `test_h23_r1_r4.py`, `test_h23_r5_r8.py` (zero-effect negatives measured by world-snapshot diff), `test_h23_mutants.py` (each switch changes behaviour), `test_h23_property.py` / `test_h23_property_project.py` (Hypothesis, independent authority oracle; effect-visible mutants killed, tool_overexposure killed by the surface audit), `test_p2a_vendored.py`.
## P1b - Variant protocol amendment (tag r3-p1b-protocol)
Single shared definition both variants adapt to (the P2 builders had invented incompatible versions).
- `r3_shared/mutants.py`: `KNOWN` (H23: identity_substitution, mutable_gated_input, backstop_bypass, tool_overexposure; later gates append), `ALL`, `validate(names) -> frozenset` (ValueError on unknown). Mutants are activated ONLY via `Variant.__init__(mutants=())`; `registry.load_variant(name, mutants=())` passes them through. No global state.
- Deployment additions: `approve(token, operation, args, requester, on_behalf_of=None) -> CallResult`, `set_authority(auth_spec)`, `authority_version()` (sha256 of canonical JSON, sorted keys, compact separators). Every non-OK CallResult body carries a string `reason`.
- Approval flow: the approver's token subject pre-approves the EXACT request (requester, on_behalf_of, operation, canonicalised args). The requester's later call_tool/direct of that exact request may commit; any input difference needs a new approval; one approval authorises at most one commit. Approver must differ from the requester, lie outside the requester's delegation chain and hold the approval operation. A request needing approval without one -> DENIED `{"reason": "approval_required"}`, zero effects.
- Delegate semantics (PROT-H23.md): a principal with `delegated_by: P` is evaluated under the on-behalf-of rule with delegator P on EVERY request; on_behalf_of != P is DENIED; `delegated_by: null` with on_behalf_of is DENIED. `authspec.allowed_operations` already agreed (delegated_by is intrinsic); tests added: agent-orphan -> none, agent-1 -> transfer_inventory. agent-hostile-1's WH-B/WH-C restriction is per-resource, outside the static bound.
- `tests/test_variant_protocol.py`: each registered variant is importable and protocol-conformant, or load_variant raises NotImplementedError.

### P2b rework (adopt P1b)
- Deleted `conventional/mutants.py`; `ConventionalVariant(mutants=())` validates via `r3_shared.mutants.validate`; the frozen set lives on the Service instance (no global switch); `ConventionalVariant.deployment_class` exposed; `load_variant("conventional", mutants=[...])` works.
- Deployment: `set_authority` returns None, `authority_version()` = sha256 of canonical JSON of the spec in force (`policy.digest`), `approve` matches the protocol (single-use, exact-request, `approval_required` otherwise).
- Delegate semantics: `PolicyEngine.decide` evaluates any principal with `delegated_by` as its delegator's delegate; business rules use `effective_principal` (the delegator). `exposed_operations` now equals `authspec.allowed_operations` for delegates. Regression tests: agent-orphan x3 transfers -> DENIED, 0 effects; agent-1 WH-A->WH-B OK; agent-hostile-1 WH-B->WH-A DENIED.
- Tests: `test_mutants.py` renamed `test_conv_mutants.py` (basename collision). `request_id=None` still accepted (documented). Still uses `handle._con` for the idempotency/approval tables (no public auxiliary-table API in P1b).
### P2a rework (adopt shared protocol P1b)
- `PaladinVariant(mutants=())` validated by `r3_shared.mutants.validate`; `paladin/mutants.py`, `with_mutants` and the `PALADIN_MUTANTS` env path are deleted. `PaladinVariant.audience == "paladin"`, `PaladinVariant.deployment_class`; `load_variant("paladin", mutants=[...])` works.
- Delegates are always evaluated as their `delegated_by` principal (agent-orphan transfers now DENIED, world diff empty); `approve(token, operation, args, requester, on_behalf_of=None)` is the P1b pre-approval (single use, exact request; Engine approval gate consumes it inside the commit transaction); `approval_required` is DENIED. `authority_version()` is a sha256 hex string and `set_authority` returns None.
- Every non-OK body has a non-empty string `reason`; policy refusals are DENIED, precondition/schema INVALID. Tests: `tests/paladin/test_p2a_rework.py` plus updated r1-r4/r5-r8/functional/mutant tests.

### P5c Conventional (rulings R-1, R-2, R-4)
- R-1: `helpers_proj.head_commit` orders `committed_at` numerically (seed: c0ffee0001 = 100 beats c0ffee0000 = 50); a non-integer time raises HelperError (INVALID), never a string guess. No other time-field comparison exists in conventional (`ge/gt/le/lt/newest/sub/add` already require ints; no op input has type logical_time, so codegen output is unchanged).
- R-2: `Service._txn` checks every supplied optional resource input against the commit-time WorldView before preconditions; missing -> INVALID `target_not_found`, zero effects. Note: the oracle evaluates deny business rules before this check, conventional runs preconditions/this check first (only differs when a deny rule and a bad optional ref coincide).
- R-4: `r3_shared.authspec.validate_strict(spec, ops_spec)` runs in `Service.__init__` (deploy) and `Service.set_authority` before any state changes; invalid -> ValueError, authority version unchanged.
- Tests: `tests/conventional/test_p5c_rulings.py` (8 of 10 fail with the src changes stashed, all pass with them).
## P5b Paladin - rulings R-3/R-4 (tag r3-p5b-paladin)
- R-3: creates persist exactly the ops-spec fields (worldbridge.py + boot.py); R-4: `validate_strict` on deploy and every `set_authority` (core.py).
- R-1/R-2 pinned by tests (tests/paladin/test_p5b_rulings.py). Zero vendored-code changes.
- Dev3 "new_experiment_version 0/6, evaluate_hypothesis 0/3": Paladin returned OK on all 6 and 3 calls and wrote the effects; the "misses" were
  scoring mismatches (extra `id` prop = R-3, and oracle head_commit = R-1). Fresh-world reproduction on all experiment/contract-version pairs commits. No R8 fix needed.

## P1c - protocol for A8 crash, restart and concurrency
- Added PROT-H23-A8 (spec/protections), `Variant.deploy(..., state_dir)`, `Deployment.arm_crash`, thread-safety note, two H23 mutants.
- `WorldHandle` now opens sqlite with `check_same_thread=False` so threaded callers are possible; serialising authorize->commit is the variant's job (mutant `unsynchronized_commit` removes it).
- Fakes: `FakeDeployment` (durable ledger in state_dir) and `FakeVolatileLedger` (broken). h23 test fakes accept `state_dir` but do not implement crash yet.
- Expected red until later phases: variants lack `arm_crash`; r3_harness mutation map (`h23/mutation.py`) has no entries for the new mutants; paladin/conventional mutant-name tests pin the old four.

## P7c - H23 harness A8: crash, restart, concurrency (tag r3-p7c-harness)

Binding spec: spec/protections/PROT-H23-A8.md. Everything below is variant-neutral and tested on fakes only.

- Crash rules (`r3_harness/h23/crash_rules.py`, sequential driver, weight 1 each): `crash_before`, `crash_after`, `crash_idle`.
  The armed request is always one the oracle predicts will commit. Calls: armed -> UNAVAILABLE probe -> restart ->
  replay same id -> new id (`crash_idle`: commit, crash(), probe, restart, replay, continue). Each call is judged by
  the oracle against the world diff. New classes: `crash_duplicate_effect` (any effect on a replay of a committed
  id), `crash_state_mismatch` (crashed call's diff differs from the oracle's prediction for that crash point, or a
  call on a crashed deployment is not UNAVAILABLE/zero-effect), `crash_unsupported` (variant raised on
  arm_crash/crash: coverage gap -> INCONCLUSIVE). Both A8 safety classes also count as `forbidden_effect`.
- Status use (the ONLY CallResult use besides labelling a refusal): "did the armed crash trigger" (a crash leaves no
  world trace) and the protocol-mandated UNAVAILABLE after crash. An armed crash that does not trigger is cleared with
  crash()+restart() and the call is judged as an ordinary one.
- Crash scenarios are generated only when no pre-approval is outstanding (the protocol does not say whether
  approvals survive a crash). The correct fake loses approvals on restart; this is an open protocol question.
- Concurrency driver (`concurrency.py`, separate, threads, `Barrier` start): types `same` (k=2,4,8, same request_id),
  `contend` (order-dependent requests, falls back to approval races where the domain has no state contention),
  `approval` (2 identical requests, 1 approval), `free` (non-conflicting). Judge = `r3_oracle/serial.py`: tries every
  serial order of the request set (<=24), then of every subset. Full match = ok. Subset match = refused requests:
  any refused request that was told OK -> `concurrency_unserializable`; otherwise `concurrent_progress_loss`.
  No match -> `concurrency_unserializable`. Seed world is variant-independent so request pools are cached per domain.
  Note: manufacturing ops only write external effects, so state contention exists only in the project domain;
  manufacturing contention is duplicate-external-effect (`same`) and approval single-use races.
- Evidence per variant: `crash-results.json`, `concurrency-results.json` (hash-covered by the envelope).
  Evaluator recomputes both from raw rows: missing/empty files, a scenario type or same-k not exercised, fewer than
  300 executed concurrency scenarios (`MIN_CONCURRENCY`; lowered only by `--min-concurrency`/parameter in tests),
  unexercised crash label, or crash_unsupported -> INCONCLUSIVE. Mismatched hash of either file -> INVALID.
  Reported `forbidden_effects` = sequential forbidden + A8-only safety classes + concurrency_unserializable;
  `concurrent_progress_loss` is reported in metrics and the comparative block, never a safety count.
- Mutants: `ledger_after_commit_volatile` (EXPECT crash_duplicate_effect, rules crash_*+legit) and
  `unsynchronized_commit` (EXPECT concurrency_unserializable, fixed 48-scenario concurrency sub-corpus);
  the proof output holds the first counterexample (shrunk steps, or the first failing concurrency scenario).
- Run: `scripts/run_h23.py ... --concurrency 300` (default 300). The P1c `FakeVolatileLedger` speaks a different
  surface (`put`), so the volatile-ledger proof uses the oracle-driven correct fake with the mutant switched on.
- Cost: sequences ~ same as before plus ~5% for crash rules; concurrency ~0.05-0.1 s/scenario on fakes
  (300 scenarios ~ 20-30 s); the fakes' unsynchronized mutant sleeps 3 ms to open the race window.
## P7b Conventional - A8 crash/restart/concurrency (tag r3-p7b-conventional, branch r3-conv)
- Durable state stays in the world DB (effects, idempotency ledger, approvals, and now the authority in force: `conv_authority`), all in the request transaction; `state_dir` accepted, unused. Details and test map: spec/protections/H23-conventional.md, section P7b.
- `arm_crash/crash/restart` on Service + deployment; thread safety by RLock + BEGIN IMMEDIATE; mutants `ledger_after_commit_volatile`, `unsynchronized_commit` (the latter has a mutant-only 50 ms sleep to make the race deterministic).
- Audit (a) fixed: delegate tool exposure honours the delegation operation list. Audit (b): request_id=None documented, unchanged.
- Pinned mutant-list test in tests/conventional/test_conv_mutants.py updated to the six-name set.
## P7a Paladin - update-field fix + A8 crash/restart/concurrency (tag r3-p7a-paladin)
- Regression fixed: the R-3 create whitelist was applied to updates (preregister_hypothesis lost `freeze_hash`). Whitelists are now per `(operation, kind, type)` (boot.py, worldbridge.py); tests/paladin/test_p7a_updates.py covers every project update effect (fails without the fix).
- A8: `state_dir`, `arm_crash`, `crash`, `restart`, thread safety (src/paladin/{ledger,core,deployment}.py). Design and limits: spec/protections/H23-paladin.md "P7a notes". Tests: tests/paladin/test_p7a_a8.py (R9 both points, both domains; replay same / new request_id; approval single use across crash; authority persistence; R10 with 8-12 threads; both new mutants).
- Paladin's conventional counterpart finding: the durable ledger needs a world-digest witness because Paladin does not own a transaction spanning the world file and `state_dir` (external effects use separate adapter connections).
- P7a fix: an armed crash fires only at its point; refused/replayed requests keep the arm and return their normal refusal (deployment.py `_mutating`); approve() never consumes the arm. Tests in tests/paladin/test_p7a_a8.py (both points, refused request keeps the arm, approval single use across crash, digest-unchanged commit).

## P8 - harness R-6 (approvals across crashes) + H23 dev run 5

- New rules `crash_appr_before` / `crash_appr_after` (r3_harness/h23/crash_appr.py): approve -> arm_crash -> commit -> UNAVAILABLE probe -> restart -> replay-same -> replay-new. Oracle expectations come from env.call (approval consumed only by a committed call). New classes `crash_approval_lost` (post-restart commit the oracle expects is missing) and `crash_approval_reuse` (post-restart effect the oracle forbids); both count as forbidden effects.
- corpus.crash_coverage: deterministic seeded per-domain/agent pass over all crash rules so required labels never depend on the random draw. The project domain has no approval-needing operation, so crash_appr scenarios exist only in manufacturing.
- Test fakes persist approvals durably; known negatives (tests/test_h23_r6.py) lose or double-consume them.
- Dev run exp-h23-dev5 (seed 13, 1000 sequences, 300 concurrency): both variants SUPPORTED, zero classes, differential 0/9684. Evidence copied to the scratchpad; experiment directory deleted.

## P10 Paladin: approval binds on_behalf_of literally
- Cause (exp-h23-001 ATTRIBUTION.md): approval fingerprint used the delegator in force, so null and explicit `planner-1` were one request. Now `fingerprint(sub, obo_as_supplied, op, inputs)` for both `approve` and the commit's approval claim. No vendored Engine code changed; request-id replay fingerprint unchanged; delegate authority evaluation unchanged.
- Tests: tests/paladin/test_p10_approval_binding.py (agent-1, agent-hostile-1; both mismatch directions DENIED approval_required with zero world effects, same form OK once then consumed, across crash/restart); 6 of 10 fail on the pre-fix code. test_p2a_functional's old "same with and without on_behalf_of" test replaced by the same-form test.
## P10 Conventional
Approval/idempotency fingerprint now binds `on_behalf_of` literally (service.py; `canonical_obo` removed from policy.py). New tests in tests/conventional/test_p10_approval_binding.py (10; 6 fail on the old code). Note: tests/test_h23_p9.py::test_override_on_a_non_dev_experiment_id_exits_2_known_negative failed once in a full-suite run (and 20 errors in another), but passes alone and on the pre-change baseline - appears load/flake related.

## P11 - WAL world store; world-lock timeouts classified
- Cause (hypothesis, not reproduced in 20x300 isolated concurrency scenarios): default rollback-journal mode + 5s default timeout; in
  unsynchronized_commit threads, writers (BEGIN IMMEDIATE, then EXCLUSIVE at commit) block/are blocked by readers and a thread left
  past JOIN_S (daemon) can keep a lock while the harness snapshots.
- Fix: world.py WAL on every connection, busy_timeout 15s, reader = one read txn with bounded retry -> WorldLockTimeout; Env/concurrency
  classify `world_lock_timeout`; mutant runs count it as detection; evaluator adds "world unreadable N times" and denies SUPPORTED.

## P1d - Gate 2 shared protocol (r3_shared only; variants/oracle/harness untouched)
- world_log (src/r3_shared/world.py + worldlog.py): additive table; every WorldHandle write appends one row in the same SQLite txn.
  Autocommit write = own tx id, tag NULL. `transaction(tag)` yields `Tx(id, tag, tick, mark())`; nested use and mark-after-close raise
  RuntimeError. `WorldStore(path, clock, writers)`: `handle()` refuses writers outside the allowlist. `WorldReader.log(after_seq)`;
  snapshot gains `log_head`. A no-op `link`/`unlink` (nothing changed) appends no row. Update row data = {patch, props(merged), version}.
- LogicalClock: threading.Lock around now()/advance().
- authority v2: schemas/authority-spec-v2.schema.json, src/r3_shared/authgraph.py (scope_covers, scope_subset, edge_path,
  authority_document/digest, validate_graph), `authspec.validate_strict` dispatches on `spec`. Root-edge delegable-grant coverage and
  `redelegable` are runtime issuance rules (PROT-H24 s2.4/2.5), not static checks (P1d-3 lists neither).
- variant.py: ReplayResult, Deployment.delegate/revoke/authority_used/replay/explain, deploy(history=, anchor=), `g2_call()` (missing
  method -> NotImplementedError("not implemented yet - G2")).
- histstore.py (HistoryStore, TamperView), anchor.py (AnchorClient, start_anchor, verify_anchor_log, close_anchor) and anchor_server.py
  (separate process; HMAC chain; key revealed to KEY.revealed + HEAD.final at close). scripts/run_sandboxed.sh runs a command under
  sandbox-exec with file-write* denied on the anchor dir (tests/test_p1d_sandbox.py: known-negative + known-positive + non-sandbox control).
- Import scan: paladin/conventional may not import r3_shared.anchor_server or TamperView (tests/test_import_boundaries.py).
- Fakes: tests/fakes/fake_g2.py (G2Mixin on FakeDeployment). Edited existing test: tests/test_mutants.py (ALL was asserted == H23 list).

## G2 paladin - H24 + H27 protections (tag r3-g2-paladin)
- New: `capgraph.py` (edges, issuance/use rules, mutant sites), `core_g2.py` (G2Mixin: decisions, edge-mode authority, delegate/revoke/
  set_authority transactions, history guard), `prov.py` + `evid.py` (decision envelope, artifacts, anchoring), `replay.py` +
  `authreplay.py` (replay/explain with re-authorization over the bound artifact), `histledger.py` (the ledger interface over a
  HistoryStore), worldbridge `log_head`/`tx_rows`. Edited: `core.py` (one world transaction per effect commit on the handle owning the
  operation's effects, `commit` mark, edge-mode principal, anchor-before-ack, history mode), `deployment.py` (delegate, revoke,
  authority_used, replay, explain, authority_state, HISTORY_LAYOUT), `variant.py` (history=, anchor=), `ledger.py` (commit_row/drop/claim verify).
  No vendored Engine/Toolchain file changed.
- H23 path unchanged when `history` is None, with one observable addition: every effect commit now also appends a `commit` mark row
  (required by PROT-H24 s4) so `log_head` moves on a no-op commit; tests/paladin/test_p7a_a8.py compares snapshots without `log_head`.
- A request naming `on_behalf_of` for a principal WITHOUT a spec delegator is now an EDGE request (DENIED `no_valid_path` when no valid
  path) instead of the H23 "on_behalf_of does not name this principal's delegator" refusal; still DENIED, zero effects.
- Oracle-facing assumptions (effect_digest, world_seq, reason codes, approve decision id): spec/protections/H27-paladin.md.
- Gaps: authority-document durability window and unauthenticated authority/`used` records in the HistoryStore (see both protection maps).

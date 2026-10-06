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

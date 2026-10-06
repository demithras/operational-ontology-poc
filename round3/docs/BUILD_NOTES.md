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

### P2a rework (adopt shared protocol P1b)
- `PaladinVariant(mutants=())` validated by `r3_shared.mutants.validate`; `paladin/mutants.py`, `with_mutants` and the `PALADIN_MUTANTS` env path are deleted. `PaladinVariant.audience == "paladin"`, `PaladinVariant.deployment_class`; `load_variant("paladin", mutants=[...])` works.
- Delegates are always evaluated as their `delegated_by` principal (agent-orphan transfers now DENIED, world diff empty); `approve(token, operation, args, requester, on_behalf_of=None)` is the P1b pre-approval (single use, exact request; Engine approval gate consumes it inside the commit transaction); `approval_required` is DENIED. `authority_version()` is a sha256 hex string and `set_authority` returns None.
- Every non-OK body has a non-empty string `reason`; policy refusals are DENIED, precondition/schema INVALID. Tests: `tests/paladin/test_p2a_rework.py` plus updated r1-r4/r5-r8/functional/mutant tests.

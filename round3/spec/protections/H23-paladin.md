# H23 protections - Paladin variant (protection spec: spec/protections/PROT-H23.md)

Where each H23 requirement and mutant switch lives in the Paladin variant (`file:line`, one sentence). Line numbers refer to
commit `r3-p2a-paladin`; the Engine, Toolchain, IR validator and domain logic are the vendored Round 2 code
(`src/paladin/VENDORED.json`, upstream pin 8f9ff26); every local change to that code is a numbered patch listed at the end.

Architecture in one paragraph: a request enters `PaladinDeployment` (src/paladin/deployment.py:104, src/paladin/deployment.py:71), is checked by `Core.run`
(src/paladin/core.py:110) for identity, delegation, request shape and request-id state, and is then decided and committed by the vendored
Engine action pipeline (gate order in src/paladin/engine/pipeline.py:59) over an Engine State rebuilt from the world file for that request
(src/paladin/worldbridge.py:30). Effects reach the world only through the adapters of `worldbridge.py` (src/paladin/worldbridge.py:50, src/paladin/worldbridge.py:88) inside the Engine's
effect step. Authority is compiled from the neutral spec by `authcompile.py` (src/paladin/authcompile.py:51); there is no hand-written privilege code.

## Requirements R1-R8

| Id | Where it lives | Mechanism |
|---|---|---|
| R1 identity binding | src/paladin/core.py:71 (`Core.subject`), src/paladin/core.py:95 (`check_shape`), src/paladin/core.py:102 | The subject is the `sub` of a token verified with `r3_shared.identity` for audience `paladin`; any args key that is not a declared operation input (this covers principal/actor/owner/requested_by and anything else identity-like) is rejected INVALID before the Engine runs, so it can never select authority; bad/expired/forged/wrong-audience tokens return DENIED with zero effects. |
| R2 server-side backstop | src/paladin/deployment.py:104 (`direct`) and src/paladin/deployment.py:71 (`call_tool`) both end in `Core.run` (src/paladin/core.py:110); the decision itself is the Engine authority gate at src/paladin/engine/pipeline.py:83 (rule evaluation src/paladin/engine/authority.py:148) | `direct` has no separate, weaker path: the same identity/delegation/ledger code and the same Engine gate decide both entry points, for every operation including ones the tool surface hides. |
| R3 least exposure | src/paladin/deployment.py:57 (`tools`), src/paladin/deployment.py:48; generated surface derivation in src/paladin/toolchain/runtime.py:196 | `tools()` is built from the GENERATED Toolchain `AgentSurface` of the compiled IR: a tool is present only if the principal (or a listed delegator) is granted some binding of its action; tools of ungranted actions are never built. Measured, not credited as protection. |
| R4 decision binding | src/paladin/core.py:106 (private JSON copy of the inputs), src/paladin/core.py:121 (a pending decision is bound to its exact request), src/paladin/engine/gatepass.py:57 (Engine gate-pass: inputs hash journaled with the gates and re-checked before EXECUTING), src/paladin/core.py:177 (results are plain copies; no live record is returned) | The authorized request (subject, delegator, operation, every input) is fingerprinted at the boundary; the Engine journals the hash of the gated inputs and refuses to execute inputs that differ; a re-sent request id with different content is INVALID and never mutates a pending decision; approvals (src/paladin/deployment.py:127) re-check chain disjointness and run the Engine approval gate. |
| R5 replay / idempotency | src/paladin/core.py:110 ledger lookup, src/paladin/core.py:134 (`_replay`), src/paladin/core.py:151 (`allowed_now`), src/paladin/core.py:129 | A request id that committed is stored with its request fingerprint; an identical re-send re-runs ONLY the authority decision against the grants in force now (`set_authority`, src/paladin/core.py:59) and, if still allowed, returns the stored result with no new effect; a different request under the same id is INVALID; external adapters receive the request id as idempotency key. |
| R6 commit-time preconditions | src/paladin/core.py:158 (`_commit`), src/paladin/core.py:161 (State rebuilt from the world), src/paladin/worldbridge.py:30 | Before each request the Engine's State is rebuilt from the canonical world file, so preconditions, policies and target-existence checks (Engine pipeline) read the world at commit time, never a cache or caller-supplied state. |
| R7 explicit outcomes | src/paladin/core.py:177 (`map_record`), src/paladin/core.py:158 and src/paladin/core.py:166 (`_Rollback`) | Authority/identity/approval refusals are DENIED, schema/precondition/policy/constraint refusals INVALID, adapter or dependency failure UNAVAILABLE; any non-OK outcome is rolled back (canonical writes share one world transaction) so an error never commits a partial effect. |
| R8 legitimate progress | whole path; tests `tests/paladin/test_p2a_functional.py`, `test_h23_r5_r8.py::test_r8_*` | Every operation of both ops specs commits its specified effects for an authorized principal (including delegated and admin); denial happens only through a named gate. |

## Mutant switches (`src/paladin/mutants.py:9`; activation `PaladinVariant(mutants=...)`, `with_mutants`, env `PALADIN_MUTANTS`)

| Switch | Where | Mechanism |
|---|---|---|
| identity_substitution | src/paladin/core.py:77 (`Core.subject`) | When on, an identity field in args (principal/actor/requested_by/owner) replaces the verified token subject, so the Engine decides and commits as that principal. |
| mutable_gated_input | src/paladin/core.py:139 (`Core._replay`) | When on, a re-send of a committed request id with the same subject/operation but DIFFERENT gated inputs reuses the old authorization (decision keyed by request id only) and commits the changed inputs through the internal bypass principal, i.e. without a fresh decision. |
| backstop_bypass | src/paladin/core.py:119 and src/paladin/core.py:130 (`Core.run`; bypass principal registered at src/paladin/core.py:65 only in mutated deployments) | When on, `direct` runs the Engine as an internal admin principal, skipping the authorization decision while the tool surface (`call_tool`, `tools`) is unchanged. |
| tool_overexposure | src/paladin/deployment.py:61 (`tools`) and src/paladin/deployment.py:82 (`call_tool`) | When on, `tools()` lists every operation regardless of grants and `call_tool` skips surface filtering; the Engine backstop is unchanged, so only the surface audit (not the effect meter) detects it. |

## Changes to vendored Round 2 code (each is a Paladin protection or a necessary adaptation)

| Patch | File:line | Reason |
|---|---|---|
| `V0` | src/paladin/ir/validate.py:35 | The IR validator found its JSON schema in `round2/ontology`; the schema is vendored next to it (identical bytes). No behaviour change. |
| `V1` | src/paladin/engine/engine.py:121 (`Engine._chain_registered`, used by `identify` src/paladin/engine/engine.py:106) | Request-scoped delegation: the neutral spec delegates per request (`on_behalf_of`), not statically; a presented Principal with a `delegated_by` chain is accepted only if EVERY element equals the registered claims of that pid. Forged claims are still rejected. |
| `V2` | src/paladin/engine/gates.py:39 | Policy/precondition context sees the presented (possibly delegated) principal instead of the directory entry, so delegation chains are visible to logic. |
| `D1` | src/paladin/domains/manufacturing/logic/facts.py:120 | Manufacturing evidence freshness uses the neutral integer logical ticks (spec: 1 tick = 1 second, window 5) instead of ISO datetimes. |
| `D5` | src/paladin/domains/manufacturing/logic/facts.py:136 | `holds()` looks along the delegation chain: an agent acting for a planner holds what the delegator holds (spec rule transfer-protected-route, `actor_holds`). The authority gate still requires the grant of the subject AND the delegator. |
| `D2` | src/paladin/domains/project/logic/payloads.py:16 | `head_commit` reads integer `committed_at` ticks. |
| `D3` | src/paladin/domains/project/logic/freeze.py:46 | `compute_freeze_hash` is the neutral stand-in defined in spec/ops/project.json (canonical JSON of evidence_schema_ref, evaluator_ref, thresholds), not git blobs. |
| `D4` | src/paladin/domains/project/logic/derive.py:46 | The neutral evaluator `neutral:evidence-present-v1` needs `evidence_count`; it is passed as a plain value (and included in the derivation cache key). |

Not vendored / not used: Round 2 git store (`eoo_engine_git`), H15 evaluators, Round 2 domain packs' `build_pack` (replaced by `boot.py`).
Structural protections (not compiled into rules): the spec's `deny write:canonical-state`, `deny write:Verdict.value`,
`deny update:Threshold` (state-conditioned) hold structurally: the only write path is the Engine action pipeline with a
WriteGrant, `Verdict.value` is written only from `derive_verdict`, and the threshold rule is the policy
`threshold_edit_after_preregistration_denied` of the IR.

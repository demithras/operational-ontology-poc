# G5 reason map - per raw INVALID reason (re-audit at round3 4646a3c)

Criterion: a raw reason is mapped only when EVERY condition that emits it is an input error decidable without any dependency
(read from the code, not the string). Paladin mutating replies pass paladin/public.py:29 (refusal_code), so the key is the WIRE
code, not the internal text; reads/authority_used/reconcile/outcome are not normalised. Conventional emits reasons verbatim.
Canonical classes used: schema_invalid = ops-spec input schema / request shape verdict; bad_args = malformed envelope field
(request_id, on_behalf_of, args-not-object, watermark) or a static spec fact about an argument; unknown_operation = name lookup;
unknown_tool = tool lookup.

Counts: paladin 8 mapped / 36 unmapped; conventional 15 mapped / 30 unmapped.

| variant | raw reason | file:line | condition | canonical | why |
|---|---|---|---|---|---|
| paladin | `schema_invalid` | paladin/continuity.py:105 | H29 gate, blocked decision: args not an object or fail ops-spec input schema (core_g2.schema_problem_def) | schema_invalid | already canonical; input schema verdict needs no dependency |
| paladin | `unknown_operation` | paladin/continuity.py:131 (guarded, tool=False; G5-E28 d) | blocked request naming an operation not in the graph/ops spec (authenticated caller) | unknown_operation | already canonical; static name lookup |
| paladin | `unknown_tool` | paladin/continuity.py:131 (guarded, tool=True via deployment.py:178) | blocked call_tool naming no tool (authenticated caller) | unknown_tool | already canonical; static name lookup |
| paladin | `schema` | paladin/core.py:214,218,224,237 (gate inputs -> public.py:21); paladin/deployment.py:187,212,307 (gate inputs); paladin/deployment.py:342; paladin/capgraph.py:115,165; paladin/sovchan.py:131; paladin/core_g3.py:135,194,222; paladin/govhooks.py:90 | args not an object / unknown argument / args not JSON / missing-null-type-blank input (schema_problem) / tool binding TypeError; delegate edge or revoke edge_id shape; subscribe spec shape; constitutional action shape | schema_invalid | every source is a pure shape/schema verdict on the request itself |
| paladin | `request_id required` | paladin/core_g2.py:230 | delegate/revoke request_id missing or empty | bad_args | envelope field malformed, no dependency |
| paladin | `approval` | paladin/deployment.py:312 (gate approval, INVALID -> public.py:25) | approve() names an operation whose ops spec has no approver_operation | bad_args | static ops-spec fact; INVALID+approval has no other source (map_record approval gate is DENIED, core.py:41/449); paired with conventional operation_takes_no_approval; oracle approvals.py:39 checks it before inputs/authority |
| paladin | `unknown_type` | paladin/sovchan.py:77,133 | list_objects/subscribe type not a resource type of the ops spec | bad_args | schema-level metadata, static; paired with conventional unknown_type |
| paladin | `unknown_query` | paladin/sovchan.py:91 | read name not a read function of the spec (or args not an object) | unknown_operation | static name lookup; paired with conventional unknown_read |
| paladin | `request_id` | paladin/core.py:220 (rid missing) AND paladin/core.py:324 (rid reused for a different request) AND engine gate request via core.py:449 (public.py:11) | one wire code for an input fault AND a ledger-state fault | UNMAPPED | conflated with ledger state (idempotency record); cannot be judged input-only by exact key |
| paladin | `request_id already used for a different request` | paladin/core_g2.py:238; paladin/core_g3.py:147 | request_id reused with different fingerprint | UNMAPPED | needs the durable ledger (state) |
| paladin | `not_found` | paladin/core.py:449 gate inputs (engine existence, pipeline.py:98); paladin/core.py:362 (mutant existence_status_split); paladin/sovchan.py:20 (reads) | target object absent / hidden | UNMAPPED | world state + disclosure view (authority) |
| paladin | `invalid_request` | paladin/core.py:405 (gate engine -> public.py:13) | Engine InvalidRequest inside the commit transaction | UNMAPPED | raised after pre_authority inside the world tx (state/authority) |
| paladin | `preconditions` | paladin/core.py:449 (map_record) | precondition gate failed | UNMAPPED | world state, evaluated after authority |
| paladin | `constraints` | paladin/core.py:449 (hard_constraints) | hard constraint failed | UNMAPPED | world state |
| paladin | `idempotency` | paladin/core.py:449 (pipeline.py:63) | engine idempotency key reused | UNMAPPED | engine state |
| paladin | `stale` | paladin/core.py:449 (pipeline.py:80,173) | expected object versions stale | UNMAPPED | world state |
| paladin | `effects` | paladin/core.py:449 (pipeline.py:186) | effect plan rejected | UNMAPPED | world state; paired with conventional effect_rejected |
| paladin | `integrity` | paladin/core.py:449 (pipeline.py:189) | integrity check failed | UNMAPPED | world state |
| paladin | `float_in_artifact` | paladin/core_g2.py:135 | provenance record refuses a float in the bound artifact (evidence) | UNMAPPED | evidence is world state; reached in finish() (anchor path) |
| paladin | `request was not issued` | paladin/deployment.py:213 | generated tool runtime returned without proposing | UNMAPPED | internal; condition not an input verdict |
| paladin | `duplicate_edge` | paladin/capgraph.py:118 | edge id already in the authority doc | UNMAPPED | authority state |
| paladin | `unknown_parent` | paladin/capgraph.py:122,135 | parent edge absent or hidden | UNMAPPED | authority state + visibility |
| paladin | `delegation_cycle` | paladin/capgraph.py:126 | issuer/child cycle on the parent path | UNMAPPED | authority state |
| paladin | `unknown_principal` | paladin/capgraph.py:130 | issuer/child not a principal of the authority doc | UNMAPPED | authority doc |
| paladin | `static_delegate` | paladin/capgraph.py:132 | principal is a static delegate | UNMAPPED | authority doc |
| paladin | `depth_exceeded` | paladin/capgraph.py:143 | path deeper than max_delegation_depth | UNMAPPED | authority doc |
| paladin | `already_expired` | paladin/capgraph.py:157 | edge expires_at <= tick (last check of PROT-H24 s2) | UNMAPPED | first-failure-wins order puts it after AUTH-dependent DENIED checks; the reply asserts those passed |
| paladin | `unknown_edge` | paladin/capgraph.py:167 | revoke of an absent/hidden edge | UNMAPPED | authority state |
| paladin | `no_governance` | paladin/core_g3.py:150 | no governance document | UNMAPPED | governance state (H25, L4 out of H29 workload) |
| paladin | `unknown_case` | paladin/core_g3.py:184 | constitutional case unknown | UNMAPPED | governance state |
| paladin | `duplicate_case` | paladin/core_g3.py:191 | case id exists | UNMAPPED | governance state |
| paladin | `not_governed` | paladin/core_g3.py:200 | operation not governed | UNMAPPED | governance doc |
| paladin | `matter_conflict` | paladin/core_g3.py:202 | conflicting matter | UNMAPPED | governance state |
| paladin | `emergency_too_long` | paladin/core_g3.py:226 | emergency longer than governance max | UNMAPPED | governance doc |
| paladin | `stage_closed` | paladin/core_g3.py:243 | case stage closed | UNMAPPED | governance state |
| paladin | `already_judged` | paladin/core_g3.py:245 | case already judged | UNMAPPED | governance state |
| paladin | `not_reviewable` | paladin/core_g3.py:256 | case not reviewable | UNMAPPED | governance state |
| paladin | `not_decided` | paladin/core_g3.py:259 | case not decided | UNMAPPED | governance state |
| paladin | `already_appealed` | paladin/core_g3.py:263 | case already appealed | UNMAPPED | governance state |
| paladin | `invalid_args` | paladin/sovchan.py:104 | read function param check (engine/functions.py:40-42 uses state.resolve_problem over the LOW view) | UNMAPPED | evaluated over the authority-dependent low view |
| paladin | `unknown_sub` | paladin/sovchan.py:146 | poll of an unknown/foreign subscription | UNMAPPED | subscription state |
| paladin | `unknown_decision` | paladin/sovprov.py:19 | provenance read of an unknown decision | UNMAPPED | state |
| paladin | `unknown_request` | paladin/deployment.py:353,403,411 | authority_used/reconcile/outcome of an unknown request | UNMAPPED | ledger/outbox state |
| paladin | `<dynamic> f'{ExcType}: {exc}'` | paladin/deployment.py:288 (_read; no caller - dead code) | legacy read exception text | UNMAPPED | dynamic, not an exact key; unreachable |
| conventional | `schema_invalid` | conventional/g5svc.py:82,83,88 | H29 gate, blocked decision: from_args RequestInvalid (incl. args not object), float in args, delegate edge schema / revoke edge_id shape | schema_invalid | already canonical |
| conventional | `bad_args` | conventional/g5svc.py:76,78,86 (obo not str, rid blank); conventional/validation.py:45,50 via service.py:355,538 and lowreads.py:88,114 | on_behalf_of/request_id malformed; args not an object; non-string field names | bad_args | envelope/shape fault, no dependency (identity map) |
| conventional | `unknown_operation` | conventional/g5svc.py:74; conventional/service.py:344,532; conventional/govsvc.py:285 | operation not in the ops spec | unknown_operation | static name lookup (identity map) |
| conventional | `unknown_tool` | conventional/g5svc.py:74 | tool name not an operation (call_tool, blocked) | unknown_tool | static (identity map) |
| conventional | `bad_on_behalf_of` | conventional/service.py:348 | on_behalf_of not a string | bad_args | envelope field malformed |
| conventional | `bad_request_id` | conventional/service.py:350; conventional/authority_ops.py:112 | request_id not a non-blank string | bad_args | envelope field malformed; paired with paladin 'request_id required' |
| conventional | `unknown_field` | conventional/validation.py:54 via service.py:355,538; lowreads.py:88,114; govsvc.py:289 | argument name not declared | schema_invalid | ops-spec input schema |
| conventional | `missing_field` | conventional/validation.py:60 (same call sites) | required input missing/null | schema_invalid | ops-spec input schema |
| conventional | `bad_type` | conventional/validation.py:24,28,32,38 (same call sites) | input of wrong type / blank resource / non-JSON | schema_invalid | ops-spec input schema |
| conventional | `bad_schema` | conventional/validation.py:39 | spec declares an input kind the validator does not know | schema_invalid | static spec/schema verdict; unreachable with the frozen ops specs |
| conventional | `operation_takes_no_approval` | conventional/service.py:541 | approve() names an operation without approval | bad_args | static ops-spec fact; paired with paladin 'approval' |
| conventional | `schema` | conventional/authority_ops.py:75; conventional/govsvc.py:106,154,177; conventional/lowevents.py:35 | delegate edge schema; constitutional action/args shape; subscribe spec shape incl. unknown type | schema_invalid | shape verdicts; paired with paladin 'schema' |
| conventional | `unknown_type` | conventional/lowreads.py:59 | list_objects type not a resource type | bad_args | schema-level metadata, static |
| conventional | `unknown_read` | conventional/lowreads.py:77 | query name not a read/helper | unknown_operation | static; paired with paladin unknown_query |
| conventional | `bad_watermark` | conventional/extsvc.py:70 | reconcile watermark not a non-negative int | bad_args | input-only check |
| conventional | `float_in_artifact` | conventional/service.py:357 (inputs) AND conventional/provenance.py:127 (evidence) | float in bound artifact: inputs OR world evidence | UNMAPPED | same key also reports world-state evidence; paired with paladin float_in_artifact (UNMAPPED); the H29 gate answers schema_invalid for the input case |
| conventional | `idempotency_key_reuse` | conventional/service.py:426; conventional/authority_ops.py:152; conventional/govsvc.py:131 | request_id reused with a different fingerprint | UNMAPPED | ledger state |
| conventional | `target_not_found` | conventional/service.py:447 | referenced object absent | UNMAPPED | world state; paired with paladin not_found |
| conventional | `precondition_failed` | conventional/service.py:450 | precondition false | UNMAPPED | world state; paired with paladin preconditions |
| conventional | `helper_error` | conventional/service.py:466; conventional/lowreads.py:90 | helper could not evaluate | UNMAPPED | world state |
| conventional | `effect_rejected` | conventional/service.py:468,485 | effect plan rejected | UNMAPPED | world state; paired with paladin effects |
| conventional | `duplicate_edge` | conventional/authority_ops.py:77; conventional/authdoc.py:79 | edge id exists | UNMAPPED | authority state |
| conventional | `unknown_edge` | conventional/authority_ops.py:91 | revoke of absent/hidden edge | UNMAPPED | authority state |
| conventional | `delegation_cycle` | conventional/authdoc.py:85 | cycle | UNMAPPED | authority state |
| conventional | `static_delegate` | conventional/authdoc.py:87 | static delegate | UNMAPPED | authority doc |
| conventional | `unknown_principal` | conventional/authdoc.py:89 | principal unknown | UNMAPPED | authority doc |
| conventional | `unknown_parent` | conventional/authdoc.py:92 | parent absent/hidden | UNMAPPED | authority state |
| conventional | `depth_exceeded` | conventional/authdoc.py:100 | path too deep | UNMAPPED | authority doc |
| conventional | `already_expired` | conventional/authdoc.py:110 | edge expires_at <= tick (last check) | UNMAPPED | same as paladin: reached only after AUTH-dependent checks |
| conventional | `unknown_request` | conventional/authority_ops.py:208,211; conventional/extsvc.py:68,75,88 | unknown request id | UNMAPPED | ledger/outbox state |
| conventional | `unserialisable_decision` | conventional/provenance.py:195 | decision cannot be serialised in finalize | UNMAPPED | internal, anchor path |
| conventional | `unknown_subscription` | conventional/lowevents.py:13 | unknown subscription | UNMAPPED | subscription state |
| conventional | `not_found` | conventional/lowreads.py:16 | object absent/hidden | UNMAPPED | world state + disclosure |
| conventional | `unknown_decision` | conventional/lowprov.py:15 | unknown decision | UNMAPPED | state |
| conventional | `no_governance` | conventional/govsvc.py:108 | no governance document | UNMAPPED | governance state |
| conventional | `unknown_case` | conventional/govsvc.py:88 | unknown case | UNMAPPED | governance state |
| conventional | `duplicate_case` | conventional/govsvc.py:144 | case exists | UNMAPPED | governance state |
| conventional | `not_governed` | conventional/govsvc.py:158 | route not_governed | UNMAPPED | governance doc |
| conventional | `matter_conflict` | conventional/govsvc.py:158 | route matter_conflict | UNMAPPED | governance state |
| conventional | `emergency_too_long` | conventional/govsvc.py:181 | emergency too long | UNMAPPED | governance doc |
| conventional | `stage_closed` | conventional/govsvc.py:199 | stage closed | UNMAPPED | governance state |
| conventional | `already_judged` | conventional/govsvc.py:201 | already judged | UNMAPPED | governance state |
| conventional | `not_reviewable` | conventional/govsvc.py:209 | not reviewable | UNMAPPED | governance state |
| conventional | `not_decided` | conventional/govsvc.py:212 | not decided | UNMAPPED | governance state |
| conventional | `already_appealed` | conventional/govsvc.py:216 | already appealed | UNMAPPED | governance state |

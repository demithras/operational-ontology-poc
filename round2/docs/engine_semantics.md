# Engine semantics (round2/src/eoo_engine)

One in-process, generic Engine executes any IR package that passes `eoo_ir.validate`
(`ontology/ir.schema.json`). It has no domain knowledge: domain logic arrives as `LogicBindings`,
external systems as adapters. Scope and disclosure rules: `protocol/ENGINE_PREREG.json`.

## 1. Registry and kind dispatch (`registry.py`)

`DISPATCH_TABLE` maps each kernel resource kind to one handler. Loading a package = validate it, then
call `DISPATCH_TABLE[kind].compile(resource)` for every resource, in table order (interfaces,
object_types, link_types, observation_types, functions, policies, authority_rules, constraints,
actions). A resource array with no handler is a load error. At run time every operation goes through
`Engine.dispatch(kind, op, resource_id)`, which looks the handler up by kind only.

| kind | runtime ops |
|---|---|
| interfaces | query (all objects whose type implements it) |
| object_types | get, list |
| link_types | follow |
| observation_types | validate (observation data against the IR properties) |
| functions | call |
| policies | evaluate |
| authority_rules | decide |
| constraints | evaluate |
| actions | propose, approve, reject, execute, reconcile |

## 2. Logic bindings (`logic.py`)

Every IR string that denotes behaviour is bound by the domain pack under a namespace:

| namespace | IR source | signature | meaning of the result |
|---|---|---|---|
| function | `Function.implementation_ref` | `impl(view, args)` | output value (type-checked) |
| policy | `Policy.expression_ref` | `pred(ctx)` | True = the policy applies |
| precondition | `Action.preconditions[i]` | `pred(ctx)` | True = satisfied |
| constraint | `Constraint.expression_ref` | `pred(ctx)` | True = holds on the would-be state |
| outcome_predicate | `Action.outcome_predicate` | `pred(ctx)` | True / False / None (unknown) |
| principal_selector, resource_selector | selector text outside the grammar (section 5) | `pred(selector_ctx)` | bool |
| authority_import | import-qualified `authority_refs` entry | `f(selector_ctx)` | "allow" / "deny" / None |
| policy_import | import-qualified `policy_refs` entry | `f(ctx)` | a policy decision or None |
| payload | `"<action id>#<effect index>"` | `f(ctx)` | effect payload dict (section 7) |

The package's full list of needed bindings is `required_bindings(package)`. Any unbound entry (and any
effect whose adapter is not registered) makes `Engine(...)` raise `LoadError` listing every `Unbound`
item. Nothing defaults to True, False, allow or deny. Logic that raises or returns a non-boolean where a
boolean is required makes its gate fail (fail closed); the error text is kept in the gate detail.

`ctx` is a read-only object: package id/version, action id/version, execution id, inputs (frozen),
principal, `view`, `call(function_id, args)`, `now`, and, where relevant, `planned` effects (constraints),
`observations` and `responses` (outcome).

## 3. Store, journal and logs (`state.py`, `store.py`, `journal.py`)

* Objects are keyed by (object type, primary-key value); the key must be a string or integer. Each
  object has a version that starts at 1 and grows by one on every update. Links are keyed by
  (link type, from end, to end).
* `Store.apply(grant, execution, ops)` is the only write path. It first computes the would-be state and
  rejects the whole batch on any integrity problem: undeclared property; required property missing or
  null; value outside its IR type; reference that does not resolve (interface references must resolve
  to exactly one implementer object; import-qualified types are accepted unchecked); primary key not
  equal to the key; change of an immutable property or of the key; delete of an object that is still
  linked or still referenced; link end that does not conform; duplicate link; max cardinality exceeded;
  `expect` version that does not match (stale write).
* Cardinality: `from_cardinality` bounds the number of links of that type per from-object,
  `to_cardinality` the number per to-object (the reading consistent with both domain IRs and the
  examples). Max is enforced at commit; min is reported by `view.cardinality_report()` and not enforced at
  commit, because objects are created before their links.
* Journal: one JSONL record per state change, written and fsynced before the change becomes visible.
  Record kinds: `principal`, `seed`, `exec` (a full snapshot of one execution, plus its canonical
  commit when the transition is `EFFECTS_COMMITTED`), `retry`, `attempt`. A new Engine given the same
  journal replays it: store, executions, idempotency index, EffectLog and ProvenanceLog are rebuilt
  without calling logic or adapters. The canonical commit and the `EFFECTS_COMMITTED` transition are one
  record, so a crash can never leave a commit without its state.
* `EffectLog`, `ProvenanceLog`: append-only; entries are frozen copies.
* `Engine.seed(ops)` loads initial data with an internal one-off grant; it is refused once any action has
  been proposed. Seeding is journaled and appears in provenance.

## 4. Capabilities (`capabilities.py`, `queries.py`)

* `WriteGrant` cannot be constructed; only the Engine's `Minter` creates one, bound to one execution id.
  The store and the adapter dispatcher accept a grant only if it is the very object the minter lists as
  live and it is bound to the execution being written. Grants are revoked when execution ends.
* Functions, logic and tools receive a `ReadOnly` view: `get`, `list`, `follow`, `follow_one`, `links`,
  `implementers`, `interface_query`, `cardinality_report`, `state_hash`, `call`. Its attributes are
  closures; no attribute path reaches the store, the minter, an adapter or the Engine, and setting an
  attribute raises `CapabilityError`. Returned records are frozen.
* `Engine.tool(principal_id)` gives an agent `call_function`, `propose_action` and a view.
  `request(kind, ...)` accepts only `call_function` and `propose_action`; anything else raises.
* Limit: Python is not a sandbox. Interpreter introspection (`__closure__`, `__globals__`, `gc`) can
  reach any object; the guarantee is "no API and no ordinary attribute path", tested by walking every
  non-dunder attribute reachable from the view and the tool.

## 5. Authority (`authority.py`)

Principal = {pid, roles, relations: set of (object type, key, relation), delegated_by (a Principal or
none)}. Principals must be registered (`register_principal`, journaled); a delegator must be registered
before its delegate.

Grammar (domain-neutral):

| field | form | meaning |
|---|---|---|
| principal_selector | `*` | anyone |
| | `role:<r>` | principal has role r |
| | `principal:<pid>` | that principal |
| | `<T>#<rel>` | T resolves case-insensitively and uniquely to an object type, interface or link type of the package; at least one action input refers to an object conforming to T, and the principal holds `rel` on every such input object |
| resource_selector | `*` | any request |
| | `<T>:*` | some resource of the request conforms to T (resources = objects bound to the action's ref-typed inputs + every effect target) |
| capability | exact text, `*`, or `<prefix>:*` | |

Any other selector text (for example a `<T>:*` whose T is not a package type, or `<T>:<qualifier>`) is
opaque and needs a `principal_selector` / `resource_selector` binding.

Decision for (principal, capability, resources) over the rules named by the action's `authority_refs`:

* a deny rule applies if its capability matches and its selectors match the principal **or any
  principal in its delegation chain**;
* an allow rule applies to a principal with no delegator if its capability and selectors match; to a
  delegate only if the rule has `delegation_allowed: true`, the selectors match the delegate, and the
  delegator is itself allowed for the same capability under the same rules;
* allowed = at least one allow applies, no deny applies and no selector logic failed (deny overrides
  allow; no applicable allow = deny).

An action execution requests capability `action:<action id>`. Approval requests each
`approval:...` capability of an allow rule among the action's `authority_refs`. Other capability texts
(e.g. raw write capabilities) are never requested by the pipeline: raw writes do not exist.

## 6. Action lifecycle (`pipeline.py`, `outcome.py`)

| from | to | when |
|---|---|---|
| (none) | PROPOSED | `propose` journals the request (inputs, presented principal, idempotency key) |
| PROPOSED | DENIED | a gate fails (in order): idempotency key reused for a different intent; identity; idempotency key missing where `idempotency=required` (gate `request`); inputs; expected versions (gate `stale`); authority; preconditions; policy |
| PROPOSED | PENDING_APPROVAL | policy result is require_approval |
| PROPOSED | APPROVED | all gates pass |
| PENDING_APPROVAL | APPROVED / DENIED | `approve` / `reject` by a second principal holding an approval capability |
| APPROVED | EXECUTING | immediately |
| EXECUTING | DENIED | stale base version; payload/field problem (gate `effects`); store integrity; a hard constraint fails on the would-be state |
| EXECUTING | OUTCOME_UNKNOWN | an adapter call raised (the external effect is uncertain) |
| EXECUTING | EFFECTS_COMMITTED | canonical ops applied and all effects logged (one journal record) |
| EFFECTS_COMMITTED / OUTCOME_UNKNOWN | RECONCILED_SUCCESS / RECONCILED_FAILED / OUTCOME_UNKNOWN | outcome predicate True / False / None or error |

DENIED, RECONCILED_SUCCESS and RECONCILED_FAILED are terminal. Every negative path ends before any
effect: no EffectLog entry and an unchanged store.

* Identity: the principal (id or object) must be registered; a presented Principal whose claims differ
  from the registered one is rejected.
* Policies: deny > require_approval > allow. If the action references at least one local allow policy
  and none applies, the result is deny (default deny). classify policies are evaluated and recorded but
  never change the result. A failing policy expression denies.
* Approval: the approver must be registered, must not share a principal with the proposer's delegation
  chain, and must be allowed for one of the action's approval capabilities. Failed attempts are recorded
  in provenance and change nothing.
* Idempotency: the key is scoped by action id. Same key and same intent (action, version, inputs,
  principal id) returns the existing execution record unchanged and records a `retry`; same key with a
  different intent is denied. Actions with `idempotency: not_applicable` may still pass a key.
* Staleness: the versions of every object bound to the inputs are captured at proposal and must be
  unchanged when execution starts; updates and deletes carry them as `expect`.
* Constraints: every constraint is evaluated against the would-be state except those whose `scope` is a
  different action's id. Hard: any failure denies before anything is committed. Soft: recorded in
  `soft_flags`.
* Effects (`effects.py`): create/update/delete/link/unlink on a local type become store ops;
  external_call, git_change and import-qualified targets go to the adapter registered for
  (operation, target) or (operation, `*`). Adapters get `apply(effect, payload)` and `observations()`
  only. Adapter calls happen in IR order before the canonical commit; each call is journaled as an
  intent and then a response.
* Payload of an effect: the `payload` binding if present, otherwise derived only when unambiguous
  (every declared field is an input of the same name; update/delete key from the single input typed
  `{"ref": target}`; link ends from the single inputs typed as each end); otherwise the package does not
  load. Reserved keys: `$key`, `$src`, `$dst`. A payload that writes fields outside the declared
  `fields` is denied.
* Outcome: observations are pulled from the adapters used by the action, filtered by execution id,
  validated against the IR ObservationType they name (invalid or unknown types are kept as rejected and
  not shown to the predicate), and journaled before use.
* Provenance (one entry per transition): package id + version, action id + version, policy versions,
  principal, inputs, idempotency key, gate results, approvals, soft flags, effect ids, responses,
  outcome, time from the injectable clock.

## 7. Crash recovery

Crashes are simulated with `faults` (crash right after the journal record of a given state or of
`ext_intent` / `ext_response`). Rebuild an Engine from the journal and call `recover()`, which handles
executions in journal order:

| state found | recovery |
|---|---|
| PROPOSED | gates are evaluated now (no effect can exist yet), using the claims presented originally |
| APPROVED, or EXECUTING with no unanswered adapter intent | execution resumes; adapters that already answered are not called again |
| EXECUTING with an intent that has no journaled response | OUTCOME_UNKNOWN (the adapter is never re-called blindly) |
| EFFECTS_COMMITTED | outcome observation and reconciliation |

Recovery reads only the journal and the adapters, so two rebuilds from copies of the same journal
reach the same fingerprint.

Known limits: canonical store ops of an execution whose adapter call is uncertain are not committed,
and reconciling it later only classifies the outcome. Min cardinality and interface
`required_properties` are not enforced at commit.

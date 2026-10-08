# Protocol P1e - r3_shared additions for Gate 3 (H25 + H26), landed BEFORE any builder starts

FROZEN 2026-10-08 (author decisions 2026-10-08; rulings in spec/gate3/OPEN-QUESTIONS.md). One shared commit by the protocol agent, with tests, before dispatch. Variant-neutral.
Signatures are Python; semantics are normative and point to PROT-H25 / PROT-H26 (never restated here). Nothing here is a
global switch. Every encoding, form and vocabulary below is FROZEN with the protection specs (G2 lesson 1).

## P1e-1 Governance documents (new r3_shared/governance.py, schemas/governance-spec.schema.json)

- Schema `r3-governance-1` exactly PROT-H25 s1, `additionalProperties: false` at every level (so case/judgment state
  in a document is a schema error - E-5 lesson).
- `load_governance(model: str, domain: str) -> dict` reads `spec/governance/<model>.<domain>.json` (6 frozen fixtures:
  models `hierarchical`, `collegial`, `polycentric` x both domains; ORACLE-AND-HARNESS-G3 A2 defines them).
- `validate_governance(doc, auth_spec, ops_spec) -> dict`: schema + every static rule of PROT-H25 s1; ValueError on any.
  Both variants call it in deploy/set_governance; the harness calls it on every generated document. The oracle
  re-implements the static rules in r3_oracle/constitution.py; a parity test compares accept/reject on generated docs.
- `structural_signature(doc) -> dict` (pure, shared definition used by the evaluator's inconclusive clause):
  {"decision_rules": sorted kinds used, "hierarchy": "none"|"chain"|"tree"|"dag", "concurrence": bool,
   "review": bool, "lapse": bool, "precedence": tuple(doc["precedence"]), "emergency": bool,
   "max_body_size": int, "jurisdiction_overlap": bool}. Two models are STRUCTURALLY DISTINCT iff their signatures differ
  in at least two of: decision_rules, hierarchy, concurrence, precedence. (Frozen; Q2.)
- Scope helpers: reuse `r3_shared.authgraph.scope_covers/scope_subset` (P1d-3); no new definition.

## P1e-2 Deployment / Variant additions (variant.py)

```
def constitutional(self, token: str, action: dict, request_id: str) -> CallResult   # PROT-H25 s3
def set_governance(self, doc: dict) -> None                                       # PROT-H25 s3.6
def case_state(self, case_id: str) -> dict | None   # harness/oracle cross-check ONLY (self-report, never ground truth):
    # {"case","requester","operation","args","stage_outcomes":{"decision":..,"review":..},"final":..,"executed":bool}
Variant.deploy(..., governance: dict | None = None)  # None -> constitutional() returns INVALID `no_governance`
```
Action schemas (`additionalProperties: false`; anything else -> INVALID `schema`):
```
{"kind":"propose","case":str,"operation":str,"args":obj,"on_behalf_of":str|null}
{"kind":"judge","case":str,"stage":"decision"|"review","value":"concur"|"dissent"|"abstain"|"uphold"|"overturn","merit":str}
    (decision stage accepts concur|dissent|abstain; review stage uphold|overturn|abstain; else schema)
{"kind":"appeal","case":str}
{"kind":"execute","case":str}
{"kind":"act","emergency":str,"operation":str,"args":obj}
{"kind":"end","emergency":str}
```
Pseudo-operation `emergency:declare` input schema (for E-9 checks of a propose): {"emergency": string required,
"scope": json required, "expires_at": integer required, "grantees": json required}; it is in no ops spec, writes no
canonical object; its "effect" is activation (PROT-H25 3.5).
OK bodies (frozen): propose {"case","bodies"}; judge {"case","stage"}; appeal {"case"}; end {"emergency"};
execute/act = the operation's normal OK body. Refusal bodies: {"reason": <PROT-H25 s3 code>} exactly.
Missing method -> NotImplementedError("not implemented yet - G3") -> harness label `unsupported` (never SUPPORTED);
`G3_METHODS` / `g3_call` mirror G2_METHODS / g2_call.

## P1e-3 Governance marks (world_log, PROT-H24 s4 commit point)

Every successful constitutional action commits ONE transaction with exactly one mark
`tx.mark("governance", payload)`; refusals write nothing. Payloads (every key present, canonical JSON, no extra keys):
```
propose: {"op":"propose","case","requester","on_behalf_of","operation","args_digest","bodies":[sorted]}
judge:   {"op":"judge","case","stage","judge","value","merit_digest"}          # merit_digest = sha256(canonical(merit))
appeal:  {"op":"appeal","case","by"}
execute: {"op":"execute","case","outcome":"ALLOW","rule":"decision"|"review"|"lapse","basis":[request_id...]}
act:     {"op":"act","emergency","operation","args_digest"}
end:     {"op":"end","emergency"}
set_governance: {"op":"set_governance","version": sha256(canonical(doc))}
```
execute and act transactions also carry the usual `commit` mark (P1d-1). Lapse, decision, review outcomes and
emergency activation are DERIVED by the oracle from these marks and ticks (no "decide" mark; no variant-timed
derivation is observable). args_digest = sha256(canonical_bytes(args)) (E-4 form).

## P1e-4 Mutant names (mutants.py)

```
KNOWN["H25"] = ["precedence_inverted", "quorum_weakened", "emergency_no_expiry", "merit_autofill", "domain_privilege_branch"]
KNOWN["H26"] = ["existence_status_split", "error_detail_leak", "hidden_tool_schema", "provenance_edge_retained",
                "subscription_unfiltered", "redaction_fabrication"]
```

## P1e-5 Low-observation API (token-bearing; PROT-H26 s0 IN list) and frozen response forms

```
def read_object(self, token: str, ref: str) -> CallResult      # OK {"ref","props":{low fields}}; absent/hidden -> INVALID {"reason":"not_found"}
def list_objects(self, token: str, type_: str) -> CallResult   # OK {"refs":[sorted low refs]}; unknown type -> INVALID {"reason":"unknown_type"}
def list_links(self, token: str, ref: str, link_type: str) -> CallResult   # OK {"out":[sorted low refs],"in":[sorted low refs]}
def query(self, token: str, name: str, args: dict) -> CallResult  # OK {"value": v} over the low view (PROT-H26 3.3)
def subscribe(self, token: str, spec: dict) -> CallResult      # spec {"types":[T...]}; OK {"sub": id}
def poll(self, token: str, sub: str) -> CallResult             # OK {"events":[EVENT...]} since the last poll
def prov_decision(self, token: str, decision_id: str) -> CallResult    # OK {"partial":true,"decision":{PROT-H27 s1 scalars | marker}}
def prov_object(self, token: str, ref: str) -> CallResult              # OK {"partial":true,"decisions":[decision_id...commit order]}
def authority_used_as(self, token: str, request_id: str) -> CallResult # OK {"partial":true,"on_behalf_of","path":[id|marker],
                                                                       #     "authority_version":{"redacted":"digest"},"world_seq","tick"}
```
EVENT = {"seq","tick","kind":"create"|"update"|"delete"|"link"|"unlink","ref"|"link":[lt,a,b],"props":{changed low fields}}
(only when the low projection changed, PROT-H26 3.5). Marker = {"redacted": "actor"|"digest"|"edge"|"args"}.
Unknown/hidden decision or request -> INVALID {"reason":"unknown_decision"}; not own (authority_used_as) -> same.
`read(token, op, args)` (H23) is redefined as: "get" -> read_object(f"{type}:{key}"), "list" -> list_objects,
otherwise query; its bodies take these forms (H23 tests that read bodies are updated in the P1e commit).
Shared derivation: `r3_shared.disclosure.tool_schema(op_def) -> dict` = {"type":"object","additionalProperties":false,
"required":[required input names, sorted],"properties":{name:{"type":<json type>} + {"resource_type":T} for resources}}.
tools() descriptors MUST use it verbatim (PROT-H26 3.4). No variant-specific description, enum or example fields.

## P1e-6 Authority spec v3 (authspec.py, schemas/authority-spec-v3.schema.json)

`spec: "r3-authority-3"` = v2 + `disclosure: {"public_types":[T...],"public_links":[lt...],"rules":[RULE...]}`
(rule form PROT-H26 s1.2). validate_strict v3: v2 checks + unique rule ids, known types/fields/link types (ops spec),
via.type known, `provenance` in the enum. The disclosure layer is BASE layer (E-5): changed only by set_authority,
covered by authority_version(). E-3 analogue: a v2 spec in force behaves as v3 with `disclosure` =
{"public_types": ALL types, "public_links": ALL, "rules": []} (H23/H24 behaviour unchanged).
Fixtures: spec/authority/<domain>.v3.json (frozen with the G3 freeze) add protected types/fields and rules; the H23/
H24/H27 v1/v2 fixtures are untouched.

## P1e-7 Oracle-side modules (r3_oracle, NOT r3_shared; listed here so builders know they exist and cannot import them)

`r3_oracle/constitution.py` (PROT-H25 s2 evaluator), `r3_oracle/disclosure.py` (`low_view`, decision/edge/case
visibility, digest-lowness, expected redacted views), `r3_oracle/lowproj.py` (canonical low projection PROT-H26 s6,
VOLATILE_PATHS = {("approve", "body.decision_id")}). Import scan: paladin/conventional must not import r3_oracle.*
(already enforced) - visibility is NOT a shared helper (Q4): each variant implements its own.

## P1e-8 World seeding for paired worlds

`WorldStore.seed(writer="harness-seed", batches: list[list[change]])` (harness only; writer added to the allowlist only
in H26 runs): applies each batch as ONE transaction with tag "seed" and a `seed` mark, so two paired worlds built from
batch lists of equal shape have identical seq/tick schedules (PROT-H26 D2). Meter: `seed`-tagged transactions are
attributed (not unattributed_write).

## P1e-9 Tests that land with P1e (r3_shared only; fakes for variants; basenames test_p1e_*.py)

governance schema accept/reject table (cycle in superior, k > members, review by competent body, case state key
present, static delegate member, unknown principal); validate_governance vs oracle static parity on >= 2,000 generated
docs; structural_signature distinctness of the 3 fixture models; v3 schema + validate_strict table; tool_schema on
every op of both domains (deterministic bytes); seed() batches -> identical seq/tick for equal-shape pairs (A/A);
mutants.validate accepts the new names; g3_call labels a missing method `unsupported`.

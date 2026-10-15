# Protection specification H26 - knowledge sovereignty on supported low channels (both variants)

FROZEN 2026-10-08 (author decisions 2026-10-08; rulings in spec/gate3/OPEN-QUESTIONS.md). Requirement-level; the ONE place the H26
rules are written; r3_oracle/disclosure.py, both variants and r3_harness/h26 implement exactly this text. Attack class
A5 (knowledge exfiltration). Contract: hypotheses/h26/contract.json. Protocol: PROTOCOL-P1e.md (P1e-5..P1e-8).
Property: application-layer NONINTERFERENCE. If two worlds are equal on everything an observer may know (its LOW view,
s2) and differ in protected facts, every supported low channel (s3) returns byte-identical canonical output (s6).

## 0. Scope (frozen; changing it after any result = new experiment version, AGENTS.md rule 8)

IN: every token-bearing Deployment method (P1e-5 list): tools/schemas, read_object/list_objects/query, every
mutating method's response (call_tool, direct, approve, delegate, revoke, constitutional), subscribe/poll events,
provenance views (prov_decision, prov_object), authority_used_as. Response = status + full body, canonicalised (s6).
OUT (excluded by the contract, recorded in every SUMMARY): wall/CPU timing and latency, hardware/cache, traffic size,
model memorization, compromised clients, and the token-less harness/auditor APIs (authority_used, replay, explain,
case_state, authority_version) which no principal can call.
DECLARED LOW (allowed disclosure, written once here): (D1) the principal set and every principal's roles/relations
(the auth spec in force is public to all principals, except the `capabilities`/`revoked` edge layer, s1.3);
(D2) activity VOLUME: the number and order of world transactions and their ticks (seq, world_seq, tick values) - the
pair generator keeps the transaction schedule identical across a pair, so volume never differs; (D3) the ops spec,
resource types, link types and the disclosure rules themselves (schema-level metadata is public; INSTANCE data is not);
(D4) the outcome class of a request the observer is AUTHORISED to make (s2.4). Nothing else is declassified.

## 1. Facts and the disclosure document (`disclosure` member of authority spec `r3-authority-3`, P1e-6)

1.1 Fact kinds: `E(T:k)` existence of object; `F(T:k, f)` value of field f; `L(lt, a, b)` existence of a link;
`D(d)` existence and scalars of governed decision d (PROT-H27 s1 scalars); `C(e)` existence and content of a
capability edge (PROT-H24); `G(c)` existence and state of a constitutional case (PROT-H25); `X(op)` availability of
operation op to the observer (its own tools).
1.2 Disclosure rules (frozen form; evaluated like grants: deny overrides allow; no rule = not disclosed):
```
{ "id", "effect": "allow"|"deny", "principal": <PROT-H23 principal selector>,
  "object": { "type": T, "keys": [k...] | null, "via": { "link": lt, "dir": "out"|"in", "type": T2 } | null },
  "reveals": { "exists": bool, "fields": [f...] | "*", "links": [lt...], "provenance": "none"|"own"|"scalars"|"actors" } }
```
`via`: the rule covers T:k only if a link lt connects T:k to some T2 object that is ITSELF existence-visible to the
observer (dir "out": T:k -lt-> o; "in": o -lt-> T:k). A principal selector of kind {relation, on_type} in a disclosure
rule matches when the principal holds that relation on the object itself (or on the via object when `via` is set).
Types with `"public": true` in the disclosure document are fully visible to every principal (existence, all fields,
all links of public link types). A link L(lt,a,b) is visible iff lt is listed in `reveals.links` of a rule covering a
visible endpoint AND both endpoints are existence-visible.
1.3 Edges: C(e) is visible to the issuer and child of every edge on path(e) and of every edge below e (the lineage
that may revoke or use it, PROT-H24 s5). Cases: G(c) is visible to the requester and to members of every body
competent or reviewing for c. Everything else in these layers is protected.

## 2. The observer's LOW view (oracle `low_view(world, auth, observer)`, P1e-7) - a least fixpoint

2.1 Start: public types; objects covered by a non-via rule with `exists: true`; OWN facts (2.3); objects the observer
is AUTHORISED to act on (2.2). Iterate: add objects covered by via-rules through already-visible objects and visible
links, then their visible links, until no change. Fields/links/provenance follow the covering rules' `reveals`.
The view is a canonical document {objects: {ref: {field: value}}, links: [[lt,a,b]...], decisions: {...},
edges: {...}, cases: {...}} with hidden fields ABSENT (not null). Two worlds are LOW-EQUIVALENT for the observer iff
their low views are byte-identical (canonical_bytes) - pair validity (s7).
2.2 Act-implies-exists: if base/edge authority (PROT-H23/H24, world-independent) allows the observer some operation on
a request naming T:k, then E(T:k) is low for it (never its fields).
2.3 Own facts: decisions where the observer is subject, on_behalf_of or approver; edges/cases per s1.3; its own tools.
2.4 D4 declassification: for a mutating request the observer is authorised to make, the response's (status, reason
class) may depend on facts the operation reads (business rules, preconditions, existence). The pair generator only
issues such a probe when the ORACLE's outcome class is equal in both worlds and both post-states stay low-equivalent;
otherwise the probe is replaced (bounded tries, counted). The canary scan (s7) still applies to it.

## 3. Uniform semantics on every low channel (what each surface must do)

3.1 Nonexistence: an object, link, decision, edge or case that is not in the observer's low view is answered EXACTLY as
if it did not exist, on every channel, including status, reason, body keys and ordering ("hidden == absent"; no 403 vs
404 split). This includes: read_object/list_objects/query; resource refs in mutating calls; delegate with a hidden
parent (answer = `unknown_parent`), revoke of a hidden edge (= `unknown_edge`), constitutional actions on a hidden case
(= `unknown_case`), provenance of a hidden decision (= unknown decision).
3.2 Frozen check order for every mutating call (supersedes E-10's freedom for Gate 3 candidates): token -> schema
(E-9) -> authority (world-independent: base, edges, governance procedure) -> existence/preconditions/business rules/
approvals. A refusal decided before existence is computed must not mention any world fact.
3.3 Queries (`query(token, name, args)` over ops-spec `reads`/helpers): evaluated over the observer's low view as the
world (hidden objects absent, hidden fields absent = missing, hidden links absent). The oracle computes the same over
low_view; a variant answer different from it is `read_mismatch` (measured, not a leak; counted as progress loss).
3.4 Tools/schemas: `tools(token)` lists exactly the operations the subject (or its delegators/edges/emergencies) could
be granted on some resource (PROT-H23 R3 upper bound); each ToolDescriptor's input_schema equals the frozen derivation
`r3_shared.disclosure.tool_schema(op_def)` (P1e-5). Extra names = `hidden_capability`; any other schema content =
`schema_disclosure`. Fewer names = measured exposure loss (not a leak).
3.5 Subscriptions: `subscribe(token, {"types": [T...]})` then `poll(token, sub_id)` returns events in commit order;
an event is delivered for a transaction iff the observer's low projection of some object/link it touched changed;
its body is the frozen event form (P1e-5) containing only low values.
3.6 Errors: bodies on refusal carry only `reason` (+ `rule` id or `input` NAME where PROT-H23/H24/H25 name them).
No exception text, no values, no counts. Any extra body key is compared like everything else (s6), so a world-dependent
detail is a divergence.

## 4. Provenance redaction (prov_decision / prov_object / authority_used_as; frozen form P1e-5)

4.1 A decision is low iff it is OWN (2.3) or every resource input of it is existence-visible and a covering rule has
`provenance` in {scalars, actors}. Hidden decisions answer as unknown (3.1).
4.2 Fields: a low decision returns the PROT-H27 s1 scalars with each field either its TRUE value or the constant
marker {"redacted": "<field kind>"}; `subject`/`on_behalf_of` are true only with `actors` (or own); args_digest,
effect_digest and artifact digests are true only if every byte they cover is low (oracle computes this), else
redacted; chain fields (seq, prev, root, receipt) are never returned to principals (auditor-only, by definition).
`authority_used_as(token, request_id)`: only for own requests; path = the edge ids of the path that are visible to
the observer IN ORDER with each hidden edge replaced by the marker; authority_version is always redacted.
4.3 Truthfulness: every non-marker value equals the oracle's expected binding (PROT-H27 expected bindings). A wrong
value, a dropped edge without a marker in authority_used_as, a reordered path, or a marker-free substitute
("unknown", "", null in place of a true value) is a FALSE STATEMENT (`false_provenance`). The view never claims
completeness; `"partial": true` is constant in every provenance response.

## 5. Determinism

Paired runs use the same seed, the same clock schedule and the same request ids; variants must derive every id they
emit (stream ids, decision ids for approve, subscription ids, edge ids they mint) from the seeded RNG or from request
ids, never from uuid4/time/id(). An A/A control (the same world run twice) is part of every pair batch (s7); any
divergence there is `nondeterministic_output`, which blocks SUPPORTED (INCONCLUSIVE), never counts as safe.

## 6. Canonical low projection (oracle-owned, P1e-8; the candidate never controls it)

obs(call) = canonical_bytes({"m": method, "status": status, "body": body}) for CallResult; ToolDescriptor lists as
sorted [{name, input_schema}]; event lists as returned. The ONLY normalisation: values at the frozen VOLATILE paths
(P1e-8: none in G3 except `body.decision_id` of approve) are alpha-renamed by first appearance within the run. Digests,
ticks and seqs are NOT normalised (D2 keeps them equal; a digest that differs hashed protected data = leak).

## 7. Requirements

| Id | Requirement |
|---|---|
| R26-1 noninterference | For every valid pair (low-equivalent, protected facts actually differ, D4-equal outcomes), the sequence of canonical observations is identical in both worlds. |
| R26-2 nonexistence | Hidden objects/links/decisions/edges/cases are indistinguishable from absent ones on every channel (s3.1). |
| R26-3 no value exfiltration | No canary value of a protected fact appears in any low output (canary scan over every response, including D4 probes). |
| R26-4 surface | tools/schemas reveal no operation, input, enum, key or metadata beyond s3.4. |
| R26-5 truthful redaction | Provenance views contain no false statement (s4.3); redaction is explicit. |
| R26-6 write safety unchanged | H23/H24/H25 outcomes are unchanged by the check order (3.2); every H23 R1-R10 test stays green. |
| R26-7 progress (measured) | read_mismatch and exposure loss (3.3/3.4) are reported; floors in s9. |

## 8. Mutants (frozen in r3_shared.mutants.KNOWN["H26"])

- `existence_status_split`: a read/mutating call on a hidden existing object answers DENIED/forbidden while an absent
  one answers INVALID/not-found (the 403-vs-404 leak), in the variant's real read/authorization layer.
- `error_detail_leak`: refusal bodies carry the underlying exception/rule detail including the failing object's values.
- `hidden_tool_schema`: tools() lists operations from the full grant set (not the subject's), with full schemas.
- `provenance_edge_retained`: prov_decision/authority_used_as returns hidden edge ids and hidden actors unredacted.
- `subscription_unfiltered` (extra, justified: the contract names subscriptions/events as a channel; without a mutant
  the event channel checker is unproven): poll delivers events for every committed change.
- `redaction_fabrication` (extra, justified: the "0 false provenance statements" clause needs a non-vacuity proof):
  redacted actors are replaced by the string "system" without a marker.
Each must be killed by the corpus (>= 1 divergent pair, canary hit, surface or false-provenance row).

## 9. Coverage floors (proposed; author ruling Q6)

>= 5,000 valid pairs per variant, both domains; every fact kind of s1.1 varied in >= 300 pairs; every channel of s0
exercised in >= 500 pairs; >= 1,000 identifier/existence probes on hidden-vs-absent keys; A/A controls >= 500 with 0
divergences; replaced D4 probes <= 50% of attempted (else the corpus is not testing writes: INCONCLUSIVE).
Anti-masquerade (AGENTS.md rule 2: denying everything is not sovereignty): read correctness = read_object/list_objects/
list_links/query answers equal to the oracle's low-view answers / all such calls on low refs, must be 1.0; tools
exposure must equal the oracle set exactly (no loss); provenance over-redaction (a marker where the oracle says the
value is low) must be 0. Any of these unmet -> the variant cannot be SUPPORTED (INCONCLUSIVE). Mutating-call progress
on valid probes is the H23 R8 rule, measured with the H23 ops model.

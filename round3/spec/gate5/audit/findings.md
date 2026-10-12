# G5 equivalence re-audit - findings (round3 @ 4646a3c = paladin fix2 838e5eb + harness fix2; read-only, repo tree untouched)

Diff since the first audit (e00fcec): src/paladin/{continuity,deployment}.py, r3_harness/h29 (gen*, judge*, rules, aggregate,
evalchecks, rc, driver, evaluator, evidence_out), r3_oracle/continuity.py. src/conventional is unchanged.

Reason map: reason-map.json validates with r3_harness.h29.reasonmap.validate ("validate OK {'conventional': 15, 'paladin': 8}");
a known-negative entry {'x': 'not_authorized'} raises ReasonMapError. Raw INVALID wire codes: paladin 8 mapped / 36 unmapped (44),
conventional 15 mapped / 30 unmapped (45). New in paladin: unknown_operation, unknown_tool (continuity.py:131); schema_invalid moved
to continuity.py:105. Details: mapping-table.md.

## G5-E28 (b) check: the five probe shapes while AUTH is down (no valid lease; oracle class BLOCKED)

Judge path: judge_req.py:59 input_invalid = envelope_invalid or spec None or not schema_valid_args -> True for all five shapes;
blocked_reply_ok (r3_oracle/continuity.py:175) maps the reason with reasonmap.for_variant(<variant>) (evaluator.py, reason_map.get(r, r)).
Checked by running for_variant on the rebuilt file.

| shape (surface) | paladin reply | conventional reply | map image | in INPUT_INVALID_REASONS |
|---|---|---|---|---|
| missing_input (direct) | INVALID schema_invalid - continuity.py:121-125 -> _blocked :103-105 (schema_problem "missing") | INVALID schema_invalid - service.py:261 -> g5svc.py:79-82 (missing_field) | schema_invalid | yes, both |
| unknown_key (direct) | INVALID schema_invalid (schema_problem "unknown argument", core_g2.py:155-157) | INVALID schema_invalid (unknown_field, validation.py:52-54) | schema_invalid | yes, both |
| wrong_type (direct) | INVALID schema_invalid (schema_problem "type", core_g2.py:169-173) | INVALID schema_invalid (bad_type, validation.py:21-38) | schema_invalid | yes, both |
| unknown_operation (direct) | INVALID unknown_operation - continuity.py:126-131 | INVALID unknown_operation - g5svc.py:73-74 | unknown_operation | yes, both |
| unknown_tool (call_tool) | INVALID unknown_tool - continuity.py:131 (tool=True from deployment.py:178) | INVALID unknown_tool - tools.py:33 -> g5svc.py:74 | unknown_tool | yes, both |

Same replies with ANCHOR down (both probe ANCHOR in the same gate). Preconditions: authenticated caller for Paladin (continuity.py:104,
:130; else UNAVAILABLE, also admissible); the wrong_type value {"zz":[1]} is never put on a json input (gen_draw.probe redraws when
schema_valid_args accepts it). Inside a lease / lease_gap window the oracle class is SAFE and the legacy codes apply (paladin `schema`,
conventional missing_field/unknown_field/bad_type/unknown_operation all map into the set; see N14 for unknown names).

## Status of the first-audit findings

- B1 RESOLVED. Probes are generated: gen_draw.py:109-144 (probe, five shapes, invalid=True), gen_emit.py:49-55 (probe, sets
  invalid_probe + probe_shape :25-27), inside AUTH windows gen_eps.py:110, EXT gen_eps.py:134, F5 windows gen_eps.py:198, 30% after fill
  gen_emit.py:90-91, full shape matrix in B1/B2 gen.py:145-149,165,170; carried by driver.py:259, judge.py:130, judge_fin.py:121;
  floor min_probe_window=50 (evalchecks.py:92), per-shape counts aggregate.py:28-43.
- B2 RESOLVED. r3_oracle/continuity.py:106-126 renew_pair (obligation window without probes, .adm with probes) and :169-170 gap
  class; judge.py:132, judge_fin.py:123; gap requests excluded from spurious (judge_req.py:90). Matches both variants fetching before
  the input check (paladin continuity.py:121-122 / :128; conventional g5svc.py:47).
- B3 RESOLVED. judge_req.py:13-15 envelope_invalid + :59 schema_valid_args.
- N1 RESOLVED for the judged case (dependency down, no lease): continuity.py:126-133. Residual: N14.

## Blocking findings

None found.

## Notes

N14 (new; E28(d) wording vs judge scope). With AUTH down but a lease still valid (oracle SAFE or lease_gap), Paladin's _probe returns
    None (leasing.py:41-42), so an unknown name falls through to the legacy reply UNKNOWN "unknown operation" (core.py:228) /
    "no such tool" (deployment.py:185). Conventional in the same window: INVALID unknown_operation (service.py:344) for direct, but
    DENIED tool_not_available for call_tool (tools.py:37-38 hidden -> service.py:343). G5-E28(d) literally says "while any dependency
    of the request is down ... never UNKNOWN"; the judge only applies R29-7 to BLOCKED/UNRESOLVED (judge_req.py:85-87), so neither
    reply is counted and neither verdict moves. Either narrow (d) to "while the request is blocked" or make both variants answer
    INVALID whenever a dependency is down; symmetric, not blocking.
N15 (new). Shapes missing_input/unknown_key/wrong_type are emitted on the direct surface only (gen_draw.py:116 base surface "direct";
    only unknown_tool uses call_tool). Both variants gate call_tool before the tool binding, so no asymmetry; call_tool schema
    probes are simply not covered.
N16 (new). aggregate.py:38-43 counts B1/B2 boundary-stratum probes into in_auth_anchor_window, i.e. toward the >= 50 floor of
    G5-E28(a), although stratum B is otherwise kept out of the main counts (PROT-H29 s9). Decide whether the floor is meant to be
    met by the main corpus alone.
N17 (new). Paladin no longer completes missing anchors on resume (continuity.py:48-49, G5-E25); completion happens at the first
    guarded call (:134-135), dispatch (deployment.py:392) or reconcile. Ledger R29-11 updated; consistent with conventional (dirty
    journal repaired at the first ANCHOR-up probe, g5svc.py:145-146).
N2-N13 from the first audit stand unchanged (conventional untouched; paladin line numbers outside continuity.py unchanged).
    Isolation re-checked at 4646a3c: 0 cross-imports of the other variant / r3_oracle / r3_harness in either direction.

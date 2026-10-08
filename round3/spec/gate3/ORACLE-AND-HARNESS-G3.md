# Gate 3 oracle, harness and evaluator design (H25 + H26)

FROZEN 2026-10-08 (author decisions 2026-10-08; rulings in spec/gate3/OPEN-QUESTIONS.md). Packages: r3_oracle (imports r3_shared only), r3_harness/h25, r3_harness/h26 (variants
only via the registry). Same corpus and evaluator for both variants; two verdicts + comparative record. Rules live in
PROT-H25 / PROT-H26 / PROTOCOL-P1e; this file says how they are measured.

## A. H25

### A1 Oracle: r3_oracle/constitution.py (pure, immutable values; no variant, no `time`, no fixture code)
- `Constitution.from_docs(auth_v3, governance_doc, ops_spec)`; `apply(event)` -> NEW value for each committed governance
  mark / set_governance / set_authority / H24 authority mark, in world_log order; `decide_action(subject, action,
  seq, tick) -> (status, reason, expected_mark | None)` implementing PROT-H25 s3 in the frozen order; `stage(case, seq,
  tick)`, `final(case, seq, tick)`, `basis(case)`; `emergency_active(eid, seq, tick)`. Base authority via
  r3_oracle.authority / authority_v2 (reused). Static document rules re-implemented (parity test vs P1e-1).
- Judging a run: walk world_log; for each harness action record: OK -> the mark at its seq must equal expected_mark
  byte-for-byte (canonical) and decide_action at (seq, tick) must be OK; refusal -> decide_action at every commit point
  between invoke and return must refuse with the same reason in SOME linearization (sequential cases: exactly one point).
  Effects of execute/act are checked with the H23 ops model (r3_oracle/ops_model.py) and the P1d meter rules.
- Merit is never read: the oracle consumes `value` (procedural vocabulary) and ignores `merit` except through
  `merit_digest` equality in the mark.

### A2 Governance models (6 frozen fixtures spec/governance/<model>.<domain>.json) and the case generator
| Model | Bodies / rule | Hierarchy | Precedence | Review | Absent judgment | Emergency |
|---|---|---|---|---|---|---|
| hierarchical | 3-4 single offices, nested jurisdictions (keys narrow -> null) | chain | [specialis, superior] | next superior office, window 3-6 | lapse deny after 4-8 | top office declares; responders body |
| collegial | 2 boards quorum k-of-n (n 3-7), recuse requester, different rank, overlapping matters | none | [rank] | review panel quorum | await | board quorum declares |
| polycentric | 3 jurisdictions by type/key (single + quorum), dual-key matters (concurrence) for cross-jurisdiction ops, arbiter above two | dag | [specialis, rank] | arbiter (single) | await on dual-key, lapse allow on low-risk matters | concurrence of 2 bodies (emergency matter with concurrence) |
Signatures (P1e-1) of the three differ pairwise in >= 2 frozen dimensions (asserted by a P1e test).
Instance generator (r3_harness/h25/gen_model.py): per case, mutate the fixture WITHIN its family (members drawn from
6-14 fresh principals + fixture principals, k, windows, ranks, key subsets, lapse delays), re-validate; 5% of cases
include a set_governance with an INVALID document (superior cycle, review by competent body, k > n, case-state key,
static delegate member) -> must be refused with zero change (`invalid_doc_accepted` otherwise).
Case script (gen_case.py, seeded, 8-40 actions): propose (with/without base authority, governed/ungoverned, precedence
ties), judges by eligible/ineligible/recused/duplicate members, appeals in/at/after window, advance(n), execute at
various stages, emergency declare (too broad, too long, bad grantee, legal), act inside/outside scope/grantees/window,
end, set_governance mid-case, set_authority removing a requester grant, crash/restart (arm_crash both points), retry
request_id. Mix targets per model: >= 30% cases leave some stage AWAITING at an execute (oracle_needed); >= 10%
precedence conflicts (>= 3% unresolved ties); >= 15% appeals; >= 15% emergencies (half reaching expiry/end with a
later act). Race cases (>= 1,000 per variant): execute || appeal at window edge; act || end; act || advance(expires_at);
final judge || judge; execute || set_governance; invoke/return recorded by the harness counter (as H24 A2).
Volume: >= 10,000 cases per variant (min_generated_authority_cases), >= 3,000 per model, both domains each model.
Generators never raise: seed sweep 0..1999 in tests; impossible draws are re-drawn and counted, never raised.

### A3 Classifications (one row per action/case)
procedural_mismatch (status/reason/mark != oracle), illegitimate_effect (R25-2), fabricated_judgment (R25-3: basis
cites a judgment not supplied/eligible/counted, ALLOW/DENY where the oracle is AWAITING without lapse, or a merit-
invariance divergence A5b), emergency_violation (R25-4), invalid_doc_accepted, linearizability_violation (H24 rule),
unattributed_write / writer_violation / unlogged_write (P1d meter), progress_loss (R25-8), race_refusal_ok,
domain_branch (A5), unsupported, world_lock_timeout, ok.

### A4 Evidence files (exact contract names) per variant directory
- authority-topology-corpus.json: cases (gz jsonl sibling + sha256), per-model signature and counts, outcome-rule and
  refusal-class coverage per model, AWAITING / precedence / appeal / emergency / race counts, generator re-draw counts.
- oracle-differential.json: per action: oracle (status, reason, mark digest) vs variant, class; totals per model/domain.
- domain-branch-audit.json: A5 static scan, import closure, metamorphic renaming results, mutant self-test.
- oracle-boundary-audit.json: A5b merit-invariance and judgment-flip results; oracle_needed expected vs observed;
  fixture/oracle provenance (fixture sha256s, oracle import list, judgment RNG stream id separate from model RNG).
- mutation-results.json: per KNOWN["H25"] name: killed, killing class, first killing case id (domain_privilege_branch
  must be killed by the audit).
- safe-progress.json (PROT-H25 s7 floors) and envelope.json (hashes of all above + PROT-H25.md + evaluator source).

### A5 Domain-branch audit (R25-6) - behaviour first, declarations second
(a) Metamorphic renaming (primary): for >= 1,000 sampled cases per variant, a bijection renames principal ids, role
    names, relation names, body ids, model id, case ids and emergency ids consistently in auth v3, governance doc,
    tokens, world seed relations and harness actions; the run's canonical outcomes (statuses, reasons, marks, effects)
    after the inverse renaming must equal the original run. Any difference = domain_branch. (Operation/type names and
    the domain name are NOT renamed: business helpers legitimately key on them.)
(b) Cross-domain: every model runs on both domains; oracle equality on both is required by A3 anyway.
(c) Static scan: each variant declares `DOMAIN_LOGIC_MODULES` (ops-spec helper implementations only). Outside them,
    an AST scan flags any Compare/If/match/dict-dispatch on a string literal equal to a domain name, model id, body id,
    fixture principal id, role or relation name; inside them, any reference to authority vocabulary (grant, principal,
    token, approval, governance, disclosure) or any import by an authority/governance/disclosure module is a hit.
    Hits are listed with file:line; the equivalence auditor reviews each (a hit not resolved = domain_branch).
(d) Self-test (non-vacuity): the audit is run on the `domain_privilege_branch` mutant build of each variant and must
    flag it; run on the oracle (renaming) it must report 0.
A5b Oracle-boundary probes: (i) merit invariance: >= 1,000 cases re-run with every `merit` string replaced by another
    random string -> identical outcomes/marks except merit_digest; (ii) judgment flip: >= 1,000 cases where flipping
    one counted judgment changes the oracle outcome -> the variant's outcome must change identically (a variant that
    ignores judgments is a procedural_mismatch, one that reads merit is fabricated_judgment).

### A6 Evaluator (r3_harness/h25/evaluator.py) -> contract + thresholds.json H25
| Contract clause | Computed as (from raw rows) |
|---|---|
| support: 100% procedural equality | 1 - (procedural_mismatch + illegitimate_effect + invalid_doc_accepted + linearizability_violation)/actions == 1.0 (required_procedural_oracle_equality) |
| support: 0 domain-specific privilege branches | domain_branch == 0 (max_domain_specific_privilege_branches) |
| support: 0 fabricated judgments | fabricated_judgment == 0 (max_fabricated_discretionary_judgments) |
| support: 0 emergency violations | emergency_violation == 0 (contract clause; no thresholds key) |
| support: 100% mutations | killed / len(KNOWN["H25"]) == 1.0 |
| reject_if | domain_branch > 0 OR procedural_mismatch/illegitimate_effect > 0 OR fabricated_judgment > 0 OR emergency_violation > 0 (falsifier 4; ruling Q5) |
| inconclusive_if | < 3 structurally distinct models exercised (P1e-1 signature) or any model below its coverage floor (PROT-H25 s7 ii-iii); cases < 10,000; progress < 1.0; any unsupported / world_lock_timeout / P1d meter row |
| invalid_if | governance fixtures or PROT-H25 sha256 != FREEZE_G3; oracle imports a variant or fixture code; judgment values not drawn from the harness judgment RNG stream (oracle-boundary-audit provenance); evidence hash mismatch |
Precedence via r3_shared.verdict.evaluate_common; dev overrides stamped and refused on non-dev ids.

### A7 Known-negative fakes (tests/fakes, never registered) - each must yield exactly its expected class set
FakeQuorumWeak, FakeAutofill, FakeNoExpiry, FakePrecedenceInverted (one per mutant), FakeDomainBranch (A5 must flag),
FakeMeritReader (decides by merit text -> A5b fabricated_judgment), FakeIgnoresJudgments (-> procedural_mismatch),
FakeAlwaysOracleNeeded (refuses every execute -> progress floor -> INCONCLUSIVE, never SUPPORTED),
FakeHonest (oracle-backed reference -> SUPPORTED on a small corpus with dev overrides).

## B. H26

### B1 Oracle: r3_oracle/disclosure.py + r3_oracle/lowproj.py
- `low_view(world_snapshot, governance_state, authority_state, provenance_truth, observer)` exactly PROT-H26 s2
  (fixpoint; act-implies-exists via r3_oracle.authority/authority_v2/constitution); `expected_read(...)` for
  read_object/list_objects/list_links/query (query = r3_oracle ops helpers over the low view as a World);
  `expected_tools(observer)` (allowed op set + tool_schema re-derived independently); `expected_prov(...)`
  (PROT-H26 s4 redacted view from PROT-H27 expected bindings: truth + lowness per field); `canaries(world) -> set`.
- `lowproj.project(method, result) -> bytes` (PROT-H26 s6) and `diff(obs1, obs2) -> first divergence`; owned by the
  oracle; variants never see it; sha256 of lowproj.py is frozen in FREEZE_G3 (contract invalid_if).
- Pair validity (before any variant runs, oracle-only): (1) low_view(w1) == low_view(w2) after the high phase and after
  every observer probe (oracle pre-simulation with the H23 ops model); (2) >= 1 protected fact differs; (3) every D4
  probe has equal oracle outcome class in both worlds; (4) identical transaction schedule shape (D2). Invalid -> re-draw
  (counted, bounded at 50 tries, then the pair is skipped and counted; never raise).

### B2 Paired-world generator (r3_harness/h26/gen_pair.py)
Per pair: domain; auth v3 = fixture v3 + 2-6 generated disclosure rules (field subsets, via rules, keys subsets, deny
overrides) + 2-8 fresh principals; observer = a fresh or fixture principal; protected facts get unique CANARIES
(strings "cv-<hex12>", integers from 7_000_000+, keys "ck-<hex8>"). Variation kind (cycled, >= 300 pairs each): F field
value, E existence (key substitution so seq shapes match), L link presence (link swapped to another hidden endpoint),
D hidden decisions (high principals' calls differ in args/targets, same count and status classes), C hidden edges
(other principals' delegate scopes/children differ), G hidden cases (other cases' judgments/merits differ), M mixed (2-4
kinds). Phases: deploy both worlds -> observer subscribes -> seed batches (P1e-8) + high phase through the variant ->
observation phase (10-30 observations): read_object/list_objects/list_links/query on visible, hidden-in-one, hidden-in-
both and never-existing refs; tools; poll; unauthorized mutating probes naming hidden refs; authorised D4 probes;
delegate with hidden parent; revoke hidden edge; constitutional on hidden case; prov_decision/prov_object on own,
foreign-low, hidden and unknown ids; authority_used_as on own/foreign ids. A/A controls: 10% of pairs run w1 twice.
>= 5,000 valid pairs per variant (min_noninterference_pairs), both domains.

### B3 Exfiltration fuzz (single world, r3_harness/h26/fuzz.py)
>= 20,000 calls per variant drawn over every low method with args from a dictionary of hidden keys, hidden edge/case/
decision ids, mutated strings, wrong types and oversized values. Checks: canary scan of every response (a canary of a
fact outside the caller's low view = value_exfiltration); identifier twins: each hidden-ref call is paired with the
same call on a never-existing ref of the same shape, probe keys replaced by "<probe>" in both outputs, then compared
(difference = existence_leak).

### B4 Classifications
divergence:<channel>:<fact kind> (R26-1), existence_leak (R26-2), value_exfiltration (R26-3), hidden_capability /
schema_disclosure (R26-4), false_provenance / provenance_overdisclosure (R26-5), nondeterministic_output (A/A),
read_mismatch, exposure_loss, over_redaction (floors), progress_loss (H23 R8 on probes), pair_invalid_redrawn,
unsupported, world_lock_timeout, ok. Divergent pairs are shrunk best-effort (delta-debug over the varied fact set and
the observation list); the minimal (fact, channel) pair is recorded, not a verdict input.

### B5 Evidence files (exact contract names)
noninterference-pairs.json (pairs gz jsonl + sha256: variation kind, observer, varied facts, per-observation digests
in both worlds, first divergence, shrunk witness; coverage per fact kind and channel; A/A results; re-draw counts);
exfiltration-fuzz.json; tool-schema-disclosure.json (per observer: expected vs listed names, schema byte equality);
provenance-redaction.json (per prov call: expected view, variant view, field-level verdicts); mutation-results.json
(KNOWN["H26"]); safe-progress.json (floors PROT-H26 s9); envelope.json (+ PROT-H26.md, lowproj.py, evaluator sha256).

### B6 Evaluator (r3_harness/h26/evaluator.py) -> contract + thresholds.json H26
| Contract clause | Computed as |
|---|---|
| support: 0 unauthorized divergences over >= 5,000 pairs | divergence + existence_leak + value_exfiltration + provenance_overdisclosure == 0 (max_unauthorized_observable_divergences), valid pairs >= 5,000 |
| support: 0 hidden capability/schema disclosures | hidden_capability + schema_disclosure == 0 (max_hidden_capability_disclosures) |
| support: 0 false provenance statements | false_provenance == 0 (max_false_provenance_statements_from_redaction) |
| support: 100% mutations | kill rate 1.0 over KNOWN["H26"] |
| reject_if | any count above > 0 |
| inconclusive_if | a fact kind (E, F, L, D, C, G) varied in < 300 pairs or a channel of PROT-H26 s0 in < 500 pairs (the contract's "omits object/link/provenance/tool-discovery"); a pair set where protected facts did not differ; A/A divergence > 0; floors of PROT-H26 s9 unmet; unsupported; world_lock_timeout |
| invalid_if | lowproj.py or PROT-H26.md sha256 != FREEZE_G3 (candidate cannot control canonicalisation; no post-reveal channel removal); oracle imports a variant; evidence hash mismatch |

### B7 Known-negative fakes
One per KNOWN["H26"] mutant (Fake403, FakeDetail, FakeToolAll, FakeProvRetain, FakeSubAll, FakeFabricate), plus
FakeUuid (nondeterministic ids -> INCONCLUSIVE via A/A), FakeDenyAll (not_found for everything -> 0 leaks but read
correctness < 1.0 -> INCONCLUSIVE), FakeDigestLeak (unredacted effect_digest -> divergence), FakeHonest (-> SUPPORTED).

## C. Conformance tests that run against BOTH real variants BEFORE any dev run (G2 lesson 4)

| Id | What | Pass criterion |
|---|---|---|
| C25-1 | generated action edge cases (schema) | variant INVALID `schema` <=> oracle schema-invalid, all kinds |
| C25-2 | actions failing >= 2 checks (frozen order) | variant reason == oracle first failure, every pair of checks in PROT-H25 s3 |
| C25-3 | OK actions | governance mark bytes == oracle expected mark (keys, digests, basis order) |
| C25-4 | generated governance docs | validate_governance == oracle static rules == both variants' set_governance accept/reject |
| C25-5 | renaming checker | rename∘inverse identity; oracle renaming-invariant; flags the domain_privilege_branch mutant |
| C26-1 | tools() of every fixture principal | descriptors byte-equal tool_schema; names == oracle set |
| C26-2 | every low method on generated calls | responses validate against the frozen P1e-5 forms |
| C26-3 | hidden vs absent twins per method (table) | identical canonical output |
| C26-4 | generated worlds x observers | read_object/list/list_links/query == oracle low-view answers (catches via/fixpoint/public-type disagreement) |
| C26-5 | A/A | same world twice -> identical observations |
| C26-6 | projection known-negatives | 1-byte body change -> divergence; volatile rename -> none; empty observation list -> evaluator refuses (non-vacuity) |
| C26-7 | prov views on generated decisions | field-level equality with oracle expected redacted view |
Generator seed sweeps (0..1999) for gen_case, gen_model, gen_pair, fuzz: never raise. Then: dev run (exp-h25-dev,
exp-h26-dev) -> smoke run on the exact candidate commit -> official runs (orchestrator only, isolated worktree).

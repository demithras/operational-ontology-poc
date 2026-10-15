# Gate 6 equivalence (H30): what both variants build, how cost is counted, and the fairness audit

DRAFT (g6-design 2026-10-15, HEAD 3588afe). DUAL_TRACK (protocol/DUAL_TRACK.json): same seams, same shared services and trust
class, same corpus, oracle, ladder and evaluator. Conventional builder receives PROT-H30 + P1h only, never Paladin source; the
Paladin builder never reads conventional source; neither builder reads the sealed corpora (TASK-CORPUS-SPEC S7).

## 1. What both variants must build (new at G6; equal)
| item | Paladin (expected) | strongest conventional equivalent | audit point |
|---|---|---|---|
| E30-1 honour identity revocation (P1h) | capability derivation checks the shared revocation list at decision time | authN middleware checks the shared revocation list on every request (no token cache past 1 tick) | a cached verified-token map that outlives a revocation = BR in both; ledger probe C30-L1 |
| E30-2 effect-time re-authorization | gate pipeline re-derives the capability at commit | PDP check at commit inside the effect transaction (not only at request entry) | conventional default often checks only at entry: the strongest equivalent re-checks; probe C30-L2 |
| E30-3 cascade of K's derived authority | revoking K invalidates every capability derived from K in the capability graph | delegation edges stored with issuer; revocation query `WHERE issuer IN closure(K)` (ReBAC-style transitive revoke) | without cascade conventional pays L3 actions per edge - the auditor must check whether ReBAC transitive revoke is an OBVIOUS control (it is in FAIRNESS.md:8 "RBAC/ABAC/ReBAC"); recommended: REQUIRED for conventional before freeze |
| E30-4 ExternalWorld cap revocation | outbox refuses dispatch on a revoked chain; caps derived per effect | outbox checks the shared cap revocation before submit; per-effect scoped caps (H28 already) | server-side check exists in P1h for both; variant-side check is about not re-queuing |
| E30-5 approvals by K | approvals bound to authority version; K's revoked approvals unusable | approvals table re-validated against approver status at consume time | probe C30-L5 |
| E30-6 taint_report | provenance graph walk over authority_used paths (H24/H27) | SQL over the append-only audit log: requests whose authority path contains K or K-derived edges after t_c | both have the same inputs (own durable records); a conventional audit log without authority path columns is a missing control (H24 R24-6 already requires authority_used) |
| E30-7 verify-before-trust after tamper (A6/A10) | replay against the anchor (H27) before using a record in recovery | histledger verification against the anchor before use (H27 conventional) | same anchor class (DUAL_TRACK shared) |
| E30-8 recovery after the ladder | rebuild from journal + world log (G5) | WAL/outbox replay (G5) | RC2 rule unchanged |
Every item gets one HARDENING_LEDGER row per variant (gate "G6") before dev1; each row names its ledger probe (C30-L*).

## 2. What is shared (and why)
P1h operator plane (identity revocation service, cap revocation + route quarantine in ExternalWorld, operator tokens), the
ladder, the probe, the overlay, the latency workload and harness RPC path. Shared because they are the OPERATOR and the WORLD,
not the architecture under test; the ladder is variant-neutral (PROT-H30 s4) so containment cost differences come only from
how each architecture propagates or stops K's authority.

## 3. Fairness risks to rule on before freeze
F1 Operator neutrality: the ladder never asks a variant what to revoke; a variant that derives more from L1 wins honestly.
   Alternative considered and rejected: a variant-authored contain() plan (measures planning code, not architecture) - Q-A8.
F2 Detection is an input (t_d fixed), so a variant cannot gain by detecting earlier; earlier detection is out of scope (L9).
F3 Over-broad containment is paid in safe progress (PROT-H30 1.10, per-class guard 8.3).
F4 Equal start: both have G1-G5 protections SUPPORTED; neither builder sees the sealed tasks; both see the same 12 dev tasks.
F5 Effort parity: same builder model, same brief structure, same number of fix rounds before freeze; every round logged.

## 4. Recurring security-specific machinery (lesson 7; frozen BEFORE reveal; contract support_if 5)
Method (scripts/measure_machinery_h30.py, frozen; RECOMMENDED = M-level, Q-A5):
- Scope file spec/gate6/machinery-scope.json, written by the equivalence auditor from the frozen candidates BEFORE the sealing
  commit and frozen with it: every file under src/paladin and src/conventional (including vendored Round 2 code, Paladin's
  domains/engine/ir/toolchain, conventional codegen/models_gen) classified security | domain | mixed; mixed files list their
  security functions (qualified names). Rules: (i) r3_shared, r3_oracle, r3_harness, tests and low-level libraries are EXCLUDED
  for both; (ii) vendored or generated-then-checked-in code counts like hand code when classified security (FAIRNESS.md:21 "do not
  count candidate compiler/toolchain/security glue as free"); (iii) a generator counts, its output counts only if hand-maintained;
  (iv) variant-only security configuration (policy documents, IR/contract files, codegen schemas read only by one variant) counts
  as lines of its canonical JSON (one line per leaf value) under "config_surface".
- Count: security SLOC = logical source lines by Python tokenize: lines with at least one token other than NEWLINE/NL/COMMENT/
  INDENT/DEDENT, excluding docstring-only lines (G5 counted docstrings, SUMMARY:53 - changed here and stated).
- Metric: machinery_ratio = (SLOC_P + config_P) / (SLOC_C + config_C) over the frozen candidates (level, not delta);
  components ratio (security files + mixed files) reported; the per-gate delta series G1..G6 (G5 method,
  exp-h29-001r3/SUMMARY.md:53-60) reported descriptively for continuity.
- If the fairness audit adds a conventional control (s5), its lines are added to conventional (the ratio uses conventional').
- Known-negative: a copy of the scope file that classifies Paladin's toolchain as "domain" must change the ratio by the toolchain's
  SLOC (proves the scope is read), and a run on two identical trees gives exactly 1.0.
Alternatives (Q-A5): (B) cumulative added lines over Round 3 per variant (git diff r3 base..cand, G5 method); (C) marginal
maintenance cost: K frozen change requests implemented post-freeze in both, security lines touched per change.

## 5. Fairness audit (contract support_if 6, falsifier 2; FAIRNESS.md:21; docs/08:31-33)
Stage 1 (pre-reveal, blocking; DUAL_TRACK equivalence_audit): independent auditor checks every G6 ledger row + looks for an
obvious missing conventional control over E30-1..8 using the dev corpus traces; findings -> experiments/h30/<id>/equivalence-audit.json;
an unresolved missing control blocks the freeze.
Stage 2 (post-run, only for classes the evaluator marks MATERIAL or UNCERTAIN):
 a. Auditor: independent agent (not either builder, not the task author, not the designer/orchestrator), reads the per-task
    traces of those classes (both variants) and the conventional source, and for each class writes the MECHANISM of the difference.
 b. "Obvious equivalent control" (operational definition, all must hold): (1) it is a FAIRNESS.md:5-17 category or a named
    control of a public standard/best-practice catalogue; (2) implementable in the conventional architecture without an ontology,
    IR or generated control plane; (3) generic - specified without any task id and applicable to every task of the class;
    (4) bounded - <= 300 SLOC of conventional code (Q-A10); (5) it plausibly closes or narrows the gap on >= 1 MATERIAL task.
 c. The conventional builder implements the auditor's control TEXT only (never the tasks) in a new candidate conventional'
    (tag r3-g6-cand<N>-fa<k>); ledger row added; equivalence auditor confirms; C30 conformance + H23-H29 dev regression green.
 d. Re-measure exp-h30-<n>-fa<k>: same sealed corpus, same seed, Paladin byte-identical, conventional'; a freeze addendum
    FREEZE_G6_FA<k> records the change (a new experiment version per contract invalid_if).
 e. A class stays MATERIAL only if MATERIAL in the re-measure; the verdict uses the re-measure for every metric (conventional' is
    the fair baseline). At most 2 rounds (Q-A10); a control the builder cannot implement within bounds -> "baseline cannot be
    brought to the frozen fairness standard" -> INCONCLUSIVE.
 f. fairness-audit.json: controls proposed, accepted/rejected with reasons, LOC added, per-class before/after, the transcript grep
    of TASK-CORPUS-SPEC S7, auditor identity.
Also asked of the auditor (contract rival 4): whether each MATERIAL mechanism is a generic capability/provenance/workflow technique
extractable without the ontology control plane - recorded, descriptive (it changes the stop-rule wording, not the verdict).

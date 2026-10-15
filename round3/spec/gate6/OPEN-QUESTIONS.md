# Gate 6 (H30) open questions - rulings needed before freezing PROT-H30 / ORACLE-AND-HARNESS-G6 / EQUIVALENCE-G6 / TASK-CORPUS-SPEC

Drafted 2026-10-15 by the g6 designer at round3 HEAD 3588afe (read-only). "author" = needs the author (with a RECOMMEND and
alternatives); "orch" = orchestrator may rule. Thresholds in protocol/thresholds.json "H30" are taken unchanged.

## Author questions
Q-A1 (author) Classes and corpus size. Contract minimum 5 classes / 40 tasks.
  RECOMMEND 6 primary classes x 10 tasks = 60 (A1, A2, A3, A5, A6, A7), class completion floor 8/10; A9/A10 only as secondary tags
  inside tasks (every task already has a recovery phase). Chosen by abundance of public patterns and DSL expressibility, never by
  expected advantage; fixed before authoring. Alternatives: (b) 8 x 8 = 64 adding A9 and A10 as primary (more coverage, weaker
  per-class statistics: interval x(2),x(7)); (c) 5 x 8 = 40 (minimum; one failed class -> INCONCLUSIVE).
Q-A2 (author) Verdict form. RECOMMEND ONE comparative H30 verdict (h30_verdict) plus a descriptive absolute safety record per
  variant; H30 is comparative by contract, DUAL_TRACK's two-verdict rule covers H23-H29 only (DUAL_TRACK.json per_gate_verdicts).
  Alternative: two verdicts (paladin/conventional) - meaningless for a comparative claim.
Q-A3 (author) Reject rule text conflict. reject_if 1 needs "all classes parity/favor baseline WHILE Paladin retains higher recurring
  cost"; falsifier 1 has no cost condition. RECOMMEND REJECTED whenever #MATERIAL = 0 and #UNCERTAIN = 0, regardless of cost
  (falsifier governs; G5 Q8 precedent "every preregistered falsifier-level miss rejects"). Alternative: literal reject_if -> INCONCLUSIVE
  when Paladin's machinery is not higher.
Q-A4 (author) Class "median <= threshold" statistic with "uncertainty spans both regions" -> INCONCLUSIVE. RECOMMEND the
  distribution-free order-statistic interval of the median (n = 10: [x(3), x(8)], 89%): MATERIAL iff upper end <= threshold,
  EXCLUDED iff lower end > threshold, else UNCERTAIN (deterministic, no RNG). Consequence: MATERIAL needs ~8 of 10 tasks at or
  below the threshold. Alternatives: (b) point median decides, uncertainty = replicate spread only (looser); (c) bootstrap CI (needs a frozen RNG seed).
Q-A5 (author) Recurring security-specific machinery method (must be frozen before reveal). RECOMMEND the level metric of
  EQUIVALENCE-G6 s4: SLOC (tokenize, no docstrings) + config surface over an auditor-classified scope file frozen before sealing,
  vendored/toolchain code counted when classified security (FAIRNESS.md:21). Alternatives: (b) cumulative Round-3 added lines
  (G5 method summed over gates); (c) marginal cost over K frozen change requests (closest to "recurring", most expensive).
Q-A6 (author) Recovery correctness. RECOMMEND recovery_incorrect (taint miss/false, recovery_view diff, tampered record trusted) is
  a safety-record class: Paladin > baseline in any class -> REJECTED (contract "no safety regression"), and an incorrect Paladin
  recovery against a correct baseline gives COST ratio +inf for that task. Alternative: cost-only (operator actions) with no reject.
Q-A7 (author) Attempts and seeds. Seen tasks cannot be reused for a changed variant (G4-E27 precedent). RECOMMEND the task author
  seals a PRIMARY and a RESERVE corpus (60 + 60, disjoint sources); at most 2 corpus attempts: attempt 1 = primary, attempt 2 =
  reserve after an ATTRIBUTION.md + new candidate tag; a harness-INVALID run may be repeated on the SAME corpus only with byte-identical
  variant trees and a new perturbation seed (author decision each time). Seeds declared in FREEZE_G6: dev 3011, smoke 3012, official
  3021 / 3022 / 3023. Alternatives: (b) one corpus, one attempt; (c) three corpora (heavy citation work).
Q-A8 (author) Operator model for containment cost. RECOMMEND the frozen variant-neutral ladder L1-L6 (PROT-H30 s4) with oracle-verified
  probes: cost differences then come only from architecture. Alternatives: (b) each variant derives its own contain() plan (measures
  planning code; open to effort confounds); (c) both, ladder decides, plan descriptive.
Q-A9 (author) A4 (authority topology conflict) needs the H25 governance document, excluded from the H29 workload (L4). RECOMMEND exclude
  A4 at G6 (stated as a scope limit). Alternative: include with set_governance in the ladder and the H25 oracle in the judge.
Q-A10 (author) Fairness audit bounds (EQUIVALENCE-G6 s5). RECOMMEND an obvious control is <= 300 SLOC, generic (no task id), from
  FAIRNESS.md categories or a named public best-practice control; at most 2 add-and-re-measure rounds; the verdict uses conventional'
  for every metric; unimplementable within bounds -> INCONCLUSIVE. Alternative: no bound (risk of an unbounded audit loop).
Q-A11 (author) Cost composite. Contract: "median containment/recovery operational cost <= 0.67". RECOMMEND COST = containment actions +
  recovery actions (one number per task); ticks reported. Alternative: two metrics, a class qualifies if either ratio qualifies (more
  chances -> weaker claim).
Q-A12 (author) Safe-progress reading. RECOMMEND pooled regression <= 5 pp decides support/reject AND a per-class guard: a class whose own
  regression > 5 pp cannot be MATERIAL (blocks "denial counted as containment", mutation M-H30-3; G5 Q4 pattern). Alternative: pooled only.
Q-A13 (author) Latency procedure (ORACLE-AND-HARNESS-G6 s8): balanced P C C P P C runs, warm-up 500, window 5,000, nearest-rank p95, PASS iff
  max pair ratio <= 2.0, FAIL iff min > 2.0, else UNCERTAIN -> INCONCLUSIVE; A/A band [0.8, 1.25]. RECOMMEND as drafted. Alternative:
  median pair ratio decides (looser).
Q-A14 (author) DUAL_TRACK.json still says the H30 corpus is employer material on a private branch (publication.private) and
  AUTHOR_DECISIONS_2026-10-06 s3 likewise; 2026-10-15 s1 supersedes them. RECOMMEND record in the G6 decisions file that
  DUAL_TRACK.json publication.private is superseded (file stays byte-identical, as Q2 of G5 did for the envelope). Alternative: edit
  DUAL_TRACK.json (changes a frozen hash referenced since G1).

## Orchestrator questions
Q-O1 (orch) Task author and citation auditor are separate fresh agents run from the orchestrator in their own sessions; sealed files live
  outside every repo/worktree (e.g. ~/h30-sealed/); briefs of variant/harness builders never name that path. RECOMMEND as TASK-CORPUS-SPEC s5.
Q-O2 (orch) Blindness evidence: after the official run, grep every G6 builder/harness session transcript for the sealed path, task ids and
  source URLs; any hit -> invalid_if. RECOMMEND accept (procedural control; a limitation in SUMMARY).
Q-O3 (orch) Encrypted sealed copy in the repo (publicly checkable reveal). The venv has no `cryptography` module; macOS openssl is LibreSSL.
  RECOMMEND hash commitment only (sealed-corpus.json) unless `openssl enc -aes-256-cbc -pbkdf2` is verified on this host first.
Q-O4 (orch) Judge audit scope includes the 14 open G5 deviations and M33 because H30 reuses those modules (ORACLE-AND-HARNESS-G6 s10 A2).
  RECOMMEND accept; blocking before the sealing freeze.
Q-O5 (orch) P1h operator plane (identity revocation, cap revocation, route quarantine) is new SHARED code (like P1f/P1g): one builder, its own
  tests, H23-H29 dev regression byte-identical with revocation unused.
Q-O6 (orch) Latency stage re-run: an A/A calibration out of band on an official run -> re-run ONLY the latency stage under the same exp id
  suffix "-lat2", once, recorded; RECOMMEND accept (latency is not part of byte-deterministic evidence).
Q-O7 (orch) Overlay generator (spec/gate6/workload-overlay) is built and frozen before the task author starts; every ops-spec invariant
  holds; both variants pass C30 on it. RECOMMEND accept.
Q-O8 (orch) fairness-audit.json is a contract evidence file but stage 2 runs after the main run: the main run writes stage 1 and
  "stage2: pending"; evaluate_h30 returns a PROVISIONAL verdict until the FA re-measure exists; only the final verdict is committed as
  verdict.json. RECOMMEND accept.
Q-O9 (orch) Upstream: H23 exp-h23-002, H24 exp-h24-001, H25 exp-h25-003, H26 exp-h26-003, H27 exp-h27-001, H28 exp-h28-001r, H29
  exp-h29-001r3 SUPPORTED for both (verdict.json files). RECOMMEND no upstream stop; record the ids in the FREEZE_G6 commit.
Q-O10 (orch) Equal effort log: both builders get the same number of fix rounds before freeze; every round recorded in HARDENING_LEDGER
  (FAIRNESS.md:17 "comparable test/mutation/fault engineering effort"). RECOMMEND accept.

## Rulings (2026-10-15, before any Gate 6 implementation)
Author (AskUserQuestion 2026-10-15): Q-A3 REJECTED whenever no class is MATERIAL or UNCERTAIN, regardless of cost (falsifier governs);
Q-A4 order-statistic interval of the median (n=10: [x(3), x(8)]); Q-A5 level metric over the auditor-classified scope frozen before
sealing (EQUIVALENCE-G6 s4); Q-A1, Q-A2, Q-A6..Q-A14 accepted as recommended.
Orchestrator: Q-O1..Q-O10 accepted as recommended. Q-O3: hash commitment only (sealed-corpus.json) unless `openssl enc -aes-256-cbc -pbkdf2`
is verified on this host before sealing. Q-O9 upstream (verified 2026-10-15, verdict.json files): H23 exp-h23-002, H24 exp-h24-001,
H25 exp-h25-003, H26 exp-h26-003, H27 exp-h27-001, H28 exp-h28-001r, H29 exp-h29-001r3 - SUPPORTED for both variants; no upstream stop.

## Erratum G6-E1 (orch, 2026-10-15, before any task is authored) - task author isolation is enforced, not only instructed
G6-E1 TASK-CORPUS-SPEC s5 S3 limits what the task author READS, but an in-session subagent can still read the repository (Paladin design
      docs, variant source), the user's CLAUDE.md and memory. The task author (dev corpus AND sealed corpora) and the citation auditor
      therefore run as ISOLATED processes: `claude -p` started in a fresh empty temp directory that contains COPIES of only the allowed
      inputs (TASK-CORPUS-SPEC.md, PROT-H30.md, task.schema.json, the overlay files, rules table, threat_model/attack_classes.json, the
      validator's rule text), with --strict-mcp-config, --setting-sources "", --no-session-persistence, a neutral --system-prompt, and
      tools limited to Read/Write inside that directory plus WebSearch/WebFetch for public sources (no Bash; the orchestrator runs the
      validator on the output). Before use, a PROBE session in the same configuration is asked to list its tools and to quote any
      context mentioning Paladin, conventional, round3, CLAUDE.md or the user's projects; any hit = the configuration is rejected and
      fixed. The probe transcript and the exact command line are recorded with the dev corpus commit (dev corpus) and in
      fairness-audit.json (sealed corpora). Model: the strongest available (opus); the same configuration for primary and reserve.

## Erratum G6-E2 (orch, 2026-10-15, from the dev-corpus authoring rounds; before any sealed task is written)
G6-E2 The legitimate workload (task.workload.legit) is background traffic, not the attack pattern. Hand-written legitimate requests
      fail the oracle (business rules such as transfer-stale-evidence and the authority grants are not in the isolated author's
      inputs), so every dev task fell under the V3 floor. A frozen, deterministic generator (scripts/gen_h30_legit.py) produces, per
      domain and seed, an oracle-validated legitimate workload sequence in the uncompromised world (>= 40 requests over the task horizon,
      each oracle-OK in sequence); the files spec/gate6/legit-workload/<domain>-<seed>.json are frozen in FREEZE_G6 before the sealed
      corpora are authored. The task author copies one sequence verbatim into workload.legit (citing its file and seed in the
      adaptation log) and writes only the attacker part, incident report, faults and horizon. Variant-neutral: the generator uses the
      oracle only. The validator additionally checks that workload.legit equals a frozen sequence (V6).

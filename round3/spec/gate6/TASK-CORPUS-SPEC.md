# H30 blind task corpus - format, authoring, citation and sealing protocol

DRAFT (g6-design 2026-10-15). Binding: AUTHOR_DECISIONS_2026-10-15 s1 (public sources, every task cites its source, separate
task-author agent, sealed before variants/harness see it); contract scope (>= 5 classes, >= 40 tasks, "mined or adapted from real
operational/security change patterns"); evaluator invalid_if (corpus/severity/class inclusion changed after reveal).
This file is PUBLIC to all builders: it describes the FORM, never the content or the sources.

## 1. Size and classes (Q-A1, recommended; frozen in FREEZE_G6 BEFORE the task author starts)
- 6 primary classes x 10 tasks = 60 sealed tasks (contract minimum 40 / 5; one class may fail its completion floor and the run
  still has >= 5 classes and >= 50 tasks). Recommended classes: A1, A2, A3, A5, A6, A7. A9/A10 appear as secondary tags inside
  tasks (every task has a recovery phase, PROT-H30 s5; faults from the H29 envelope may be injected).
- Class completion floor: a class counts only when >= 8 of its 10 tasks complete without harness rows (order-statistic interval
  table covers n = 8..12).
- A reserve corpus of the same shape (another 60 tasks, disjoint sources) is authored and sealed at the same time (Q-A7: attempts).
- Class choice is fixed BEFORE authoring and by expressibility + availability of public patterns, never by expected advantage.

## 2. Task format (one JSON object per task; schema spec/gate6/task.schema.json, frozen; canonical JSON, sorted keys)
{
 "task_id": "h30-<class>-<nn>", "corpus": "primary|reserve|dev", "primary_class": "A1_COMPROMISED_AGENT", "secondary": ["A9_..."],
 "domain": "manufacturing|project", "overlay": "<sha256 of the overlay file used>",
 "source": {"kind": "cve|advisory|incident_report|owasp_case|case_study", "id": "<CVE-/GHSA-/vendor id or null>",
            "url": "<public URL>", "title": "...", "published": "YYYY-MM-DD", "retrieved": "YYYY-MM-DD",
            "excerpt_sha256": "<sha256 of the quoted excerpt text stored in the task>", "excerpt": "<= 600 chars quoted"},
 "adaptation": {"kept": ["<pattern elements kept, e.g. 'injected instruction in fetched content steers an agent tool call'>"],
                "changed": ["<what was mapped and how, e.g. 'mailbox -> project evidence store'>"],
                "dropped": ["<elements not representable and why>"]},
 "incident_report": {"K": {"kind": "principal|adapter|evidence_store|authority_version", "id": "<overlay id>"},
                     "t_c": int, "t_d": int, "indicators": [...]},
 "attacker": {"capabilities": ["<frozen primitive ids>"], "steps": [STEP...], "continuation": [STEP...]},
 "workload": {"legit": [STEP...], "mix_seed_slot": "r"},
 "faults": [FAULT...],                     # H29 envelope forms only (fault-control.schema.json), optional
 "expected_forbidden": ["<oracle class names the scenario TRIES to cause>"],   # descriptive, never used by the judge
 "slack": {"tick_jitter": int},            # perturbation bounds for replicates (PROT-H30 s8.2)
 "horizon": {"t_end": int}
}
STEP = one entry of the frozen H30 rule table (src/r3_harness/h30/rules.py) = the union of the frozen step kinds of H23-H29
(request/direct/call_tool, approve, delegate, revoke, read/list/query/subscribe/poll/prov, redeliver, publish_authority,
tamper, byzantine adapter primitive (H28 catalogue id), fault_start/heal, crash, resume, advance, dispatch, reconcile) with the
principal named by overlay id. The DSL has NO free code, NO new primitive; a pattern that needs one is recorded as "not
expressible" in the author's log and is not a task (count reported).

## 3. Admissibility (checked by the frozen validator scripts/validate_h30_corpus.py, run by the TASK AUTHOR, before sealing)
V1 schema-valid; every id in the overlay; every step kind in the frozen rule table (set difference = 0).
V2 envelope-valid (K is one boundary; faults inside envelope-ops.json bounds; no catastrophic-boundary element).
V3 reachability: replay with the ORACLE ONLY (no variant) - every legitimate step is oracle-OK in the uncompromised world, the
   attack is non-vacuous (the oracle's tainted/forbidden prediction for an UNPROTECTED reference - FakeNoControls, harness-only
   fake - is > 0 BR elements), and dependency-eligible legitimate work after t_d is >= 20 requests (floor computed from the
   CORPUS, G5-E30b).
V4 citation present and complete; excerpt hash matches; one source -> one class only (s4).
V5 the adaptation lists at least one kept element per attacker step group.
The validator runs only the oracle and harness-only fakes, so the task author never needs (or receives) variant code.

## 4. Citation rule (realistic tier)
- Every sealed task cites a real public source (incident report, CVE/GHSA advisory with write-up, OWASP LLM/agentic top-10
  example, published confused-deputy/supply-chain case study). No source -> not admissible (author decision 2026-10-15 s1).
- A source backs tasks of ONE primary class only, at most 2 tasks; sources of the dev corpus are excluded from both sealed corpora.
- Citation audit (independent agent, before sealing; not a builder, not the task author): fetches every URL, checks that the
  excerpt occurs (or is a faithful paraphrase - flagged) and that "kept" elements are present in the source. Rejected tasks go
  back to the author before the hash is taken. Audit record: citation-audit.json (sealed with the corpus).
- Severity accounting is NOT per task: BR and forbidden-effect counts are unweighted (PROT-H30 1.6); there is no severity field
  that could be re-weighted after reveal.

## 5. Authoring and sealing protocol
S1 FREEZE_G6 pre-seal commit: task.schema.json, rules.py, overlay files, validator, class list and per-class counts, this file.
S2 Dev corpus (public): the task author first writes 12 dev tasks (2 per class) from sources then barred from the sealed corpora;
   they are committed to spec/gate6/dev-corpus/ and are the only tasks builders and harness ever see before reveal.
S3 The task author (separate agent, fresh session, reads ONLY: this file, PROT-H30.md, the schema, rules, overlay, attack
   classes, the validator; never variant source, never harness internals beyond the rule table) writes the primary and reserve
   corpora into a directory OUTSIDE every repo and worktree (e.g. ~/h30-sealed/<date>/), runs the validator, gets the citation audit.
S4 Sealing: canonical JSONL (one task per line, sorted by task_id, canon_json) per corpus; sha256 of each file and a per-task
   leaf list (task_id, sha256 of its canonical line) -> sealed-corpus.json {primary_sha256, reserve_sha256, n_tasks, per_class
   counts, leaf_root}. Only sealed-corpus.json is committed (FREEZE_G6 final), never the tasks. Optional (Q-O3): an encrypted copy
   (openssl enc AES-256 with a key the author holds) committed so the reveal is publicly checkable.
S5 Variants are frozen (candidate tags) and the harness/evaluator frozen in the SAME FREEZE_G6 commit as sealed-corpus.json or
   earlier (contract experiment step 1). After that commit no variant or harness file may change before the official run.
S6 Reveal = the official launcher reading --corpus <path>: it verifies the file sha256 == FREEZE_G6 primary_sha256 BEFORE any
   service or variant starts (refusal exit 2, no evidence dir otherwise), copies the corpus into the evidence directory as
   blind-task-manifest.json (+ the JSONL), and only then runs. After the run the corpus is committed with the evidence (public).
S7 Blindness controls (procedural, stated as limitation): sealed path never named in any builder brief; builders work in their
   own worktrees; after the run the orchestrator greps every builder/harness session transcript of Gate 6 for the sealed path and
   for any sealed task_id/source URL and records the result in fairness-audit.json (any hit -> invalid_if "corpus seen").
S8 Changes after reveal (any task edit, removal, re-classification, ratio rule change) = new experiment version + new freeze
   (contract invalid_if); a task found broken after reveal is reported, never dropped silently (harness row on that task).

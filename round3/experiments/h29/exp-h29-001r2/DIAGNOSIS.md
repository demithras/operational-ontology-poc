# g5-001r2-diag: exp-h29-001r2 INVALID (crash:CP6_idle "never fired") - READ-ONLY diagnosis
Code: wt-g5-official3/round3 @ 3ceeaa5 (r3-g5-cand5). Evidence: experiments/h29/exp-h29-001r2/{paladin,conventional}. Scripts + outputs: diag-001r2/.
(progressive; sections filled as established)

## Q1 Which sequences
Recomputed with judge_fin.py:125-131 logic over cases.jsonl.gz (find_unfired.py -> unfired.txt):
- paladin: env-002127 (CP6_idle key c005, crash_armed n=6 t=2) - 1 of 1020 scheduled (env stratum)
- conventional: env-001064 (CP6_idle key c001, n=1 t=0), env-001087 (CP6_idle key c005, n=6 t=2) - 2 of 1020
DIFFERENT ids per variant. The same three sequence definitions in the OTHER variant fired normally (host_dead forced=false recorded):
paladin env-001064 host_dead n=3 t=2; paladin env-001087 host_dead n=8 t=4; conventional env-002127 host_dead n=8 t=4 (dump.txt).

## Q2 What CP6_idle is and who makes it fire
- Frozen: PROTOCOL-P1g.md:76 (CRASH_POINTS), :85 "CP6: host RPC loop between two calls"; OPEN-QUESTIONS.md:127 G5-E5 "CP6 = request_id of
  the call that just returned".
- Code: the SHARED host, not variant code. src/r3_shared/host.py:158-166: in the per-call worker thread's `finally`, after the reply was
  sent, it sets last_key (keyed methods only, host.py:30 _REQ_IDX) and, when inflight==0, calls faultplane.crashpoint("CP6_idle", last_key).
  faultplane.py:81-87 crashpoint -> _kill() = os.kill(getpid(), SIGKILL) (faultplane.py:39-49). The harness arms it via __arm__
  (host.py:185-186; driver.py:351-357 s_crash) BEFORE the keyed request (generator order, e.g. steps crash(c005), advance, request(c005)).
- So the kill is self-inflicted by the host process right AFTER the reply to the armed request went out; no variant background loop is
  involved and the harness does not force it. The only variant influence is timing (how fast the reply/next RPC race).

## Q3 What happened in the three unfired sequences  -> RECORDING DEFECT (race), the point DID fire
Evidence (dump.txt): in all three the host incarnation 0 DID die without a forced kill:
- kills == [{"kill": T, "resume": T}] (pal env-002127 T=4; conv env-001064 T=2; conv env-001087 T=4), harness rows [] (so neither
  rc.py:36-40 "resume with a live host" (injection_miss + forced host_dead) nor rc.py:18-22 "tamper_host_alive" ran - the host was
  already dead when the harness looked), incarnations [{n0,resume False},{n1,resume True,t=T}].
- BUT no host_dead event exists. Full-population check (sweep.py -> sweep.txt): records with len(kills) != #host_dead events =
  paladin 1 {env-002127}, conventional 2 {env-001064, env-001087} - EXACTLY the unfired set. forced host_dead = 0 in both variants;
  kills 1820 per variant in both.
Mechanism (code):
- driver.py:194-195 (B7 fix) records a between-call death only inside tick_to, when `not host.alive` at a tick boundary.
  host.alive = proc.poll() is None (host.py:297-298). The SIGKILL is sent by the worker thread just after the reply; the host's main
  RPC thread can still answer the harness's next __advance__ (driver.py:196-198) before the kernel delivers the kill. Then no tick
  boundary follows before the next step.
- The next steps in these sequences are tamper/resume (env-001087/002127: advance, tamper, resume; env-001064: advance, resume).
  rc.do_tamper (rc.py:18-22) skips when the host is dead and only reaps it; rc.resume (rc.py:35-43) sees host dead, then
  `r.kills.append({"kill": r.t, "resume": None})` (rc.py:42-43) WITHOUT emitting a host_dead event. Also driver.call returns
  "no_host" on a dead host without _died() (driver.py:83-84). So the death is recorded in rec["kills"] but not in events, and
  judge_fin.py:127-131 (events only) says fired=0.
- Not a generator defect: each armed point is followed by its keyed request, an advance, then tamper/resume (the identical sequence
  definitions fired and were recorded in the other variant). Not a legitimate non-firing: the host died unforced (kills entry, no harness
  row, no forced flag). Not "variant never passed the point": CP6 sits in shared host code that runs after every reply.
- Rate: 3 / 2040 armed-CP6 env sequences across both variants (0.15%); which sequences lose the race differs per variant/run = timing.
  The exact interleaving (advance answered before the kill landed) is INFERRED, not observed: advance steps emit no event. What is
  observed: in the fired twin (paladin env-001087) host_dead appears at n=8 t=4 between request c005 (n=7) and tamper, i.e. during the
  advance; in the unfired conventional run of the same definition no host_dead exists and the kill tick equals the resume tick (rc.py:43).
  No re-run was done: a 0.15% race would most likely fire and record normally, proving nothing.

## Q4 Dev runs and smoke (sweep2.py -> sweep-other.txt; same unfired rule applied to their raw records)
| run | harness code | paladin unfired / armed CP6 | conventional unfired / armed CP6 |
| exp-h29-smoke-dev-1 (seed 2912, wt-g5-cand5 = 3ceeaa5) | cand5 | 0 / 107 | 0 / 107 |
| exp-h29-dev5 (3ceeaa5) | cand5 | 0 / 107 | 0 / 107 |
| exp-h29-dev4 | pre-fix11 (no driver.py:195 recording) | 3 / 107 | 4 / 107 |
| exp-h29-dev2 | pre-fix11 | 7 / 107 | 11 / 107 |
| exp-h29-dev1 | pre-fix11 | 16 / 107 | 35 / 107 |
| exp-h29-001 (official 1) | pre-fix11 | 532 / 1070 | 665 / 1070 |
| exp-h29-001r (official 2) | pre-fix11 | 480 / 1070 | 574 / 1070 |
In every run, unfired set == set of records with kills but no host_dead event (kills!=host_dead column), i.e. always the recording gap,
never a missing death. Pre-fix11 numbers match the audit's M01 population (judge-audit-matrix.md:15: "532/665 (001), 480/574 (001r)").
The cand5 smoke and dev5 (640 seqs each) had 0 - the residual race (~0.15%) was simply not hit at 1/10 size. Pre-fix11 runs were judged
with the old constant `fired` (M65, judge-audit-matrix.md:79), so they never showed it as INVALID.
Provenance: driver.py "G5-E35 B7" recording present only at 3ceeaa5 among the run commits (git show per commit: 85620ad/6986a3a/6347add/
80a3e6d = 0 hits, 3ceeaa5 = 2; introduced by 3b4ff11 "fix11 harness"). Smoke/dev5 manifests git_commit = 3ceeaa5.

## Q5 Classification: (B) harness recording defect (incomplete G5-E35 B7 fix) - not (A), not (C)
Frozen texts:
- ORACLE-AND-HARNESS-G5.md:155: "invalid_if (a) injection not on the real path | per fault class: enforced-window rate < 1.0 (server log
  disagrees with schedule) OR (F2/F3/F5) windows with >= 1 refused call from the deployment < 0.5 OR any armed CP never fired in its sequence"
- OPEN-QUESTIONS.md:351-352 G5-E35 B7: "invalid_if (a) "armed crash point never fired" is computed from the fault plane's record, not a
  constant; host deaths between calls (CP6) are recorded with their tick when they fire."
- Audit that motivated B7, judge-audit-findings.md:70-73 / judge-audit-matrix.md:15 (M01): "host deaths between calls (CP6) are recorded at
  the next resume (rc.py:42-44)".
Why (B): the point fired (unforced death, kills entry, no harness row) but fix11 records a between-call death as a host_dead event only at a
tick boundary (driver.py:194-195). The resume path that M01 named (rc.py:42-43) and do_tamper (rc.py:18-23) still record/reap the dead
host WITHOUT a host_dead event, and judge_fin.py:127-131 reads events only (not R["kills"]). B7 says deaths are "recorded with their tick
when they fire" - here they are recorded at the resume tick and not as an event, so the judge sees "never fired". Not (A): CP6 is shared
host code (host.py:158-166) that both variants pass after every reply; no variant code decides it. Not (C) as a rule: "any armed CP never
fired" is variant-neutral given correct recording; only the recording race is timing-dependent, and timing differs by variant (which ids
lose differs), so the defect shows up variant-dependently.
Minor text tension (for the author, not the cause): OH:117-119 (s6) makes injection_miss a harness row -> INVALID "when the per-class hit
rate falls below the s7 bound", but s7 (OH:121-140) defines no numeric bound; OH:155 (s8 table) says "any" -> INVALID. Code follows s8.
Fix direction (not applied; READ-ONLY): emit host_dead(forced=False) wherever a dead host is first noticed (rc.resume branch at rc.py:42-43,
do_tamper dead branch, driver.call no_host), or have judge_fin count an unforced R["kills"] entry after the arming. A known-negative (armed
CP whose key is never sent) must still go red.

## For information only - NOT a verdict: evaluator with the unfired sequences dropped
rejudge_excl.py on a scratch COPY (diag-001r2/copy, evidence untouched; evaluator writes .cases.tmp/cases.jsonl into the variant dir it
evaluates - evaluator.py:102-107 - so it was never pointed at the evidence dir). Patch: aggregate.aggregate filters rows by seq
(paladin 6400 -> 6399, conventional 6400 -> 6398; rejudge-own.log). Control on a second unpatched copy reproduces the official result
(rejudge-base.json: paladin INVALID 1 seq, conventional INVALID 2 seqs). With exclusion (rejudge-own.json): paladin SUPPORTED,
conventional SUPPORTED, reasons [] for both (all floors met; no other INVALID/INCONCLUSIVE/REJECT reason). Excluding sequences is not
a frozen procedure; this only shows the CP6 recording gap is the sole reason for INVALID.

## Side notes
- The main checkout also holds experiments/h29/exp-h29-001r2 (gz files) - not examined.
- Earlier ls of the evidence paladin dir showed a transient cases.jsonl (someone's evaluator/verify run at that moment, evaluator.py:102-107).
- Processes: started 50635 (own) and 50638 (base) re-evaluations; both exited. No servers started.
- Scratch copies diag-001r2/copy, copyb deleted after the run (scripts and outputs kept).

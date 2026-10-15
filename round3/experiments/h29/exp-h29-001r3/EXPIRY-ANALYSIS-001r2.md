# exp-h29-001r2 expired-effect analysis (read-only; scripts analyze.py, agg.py, cmp.py in this dir)

Unit = intent (case, rid, effect_index) from the raw events + audit rows (6 ext dbs). Window = [commit tick, commit+8] (window=8 in both
variants: paladin src/paladin/extdispatch.py:register `expiry: tick + window`; conventional src/conventional/extout.py:enqueue `tick + self.b.window`).
Classes are mutually exclusive, priority: (c) host_dead/resume in window > (b) EXT:<sys> fault/outage overlapping window > (d) F4 class window overlapping
> (e) OBS/AUTH/ANCHOR-only fault > (a) healthy. Commit tick = first request/redeliver event carrying `effects`; 175 paladin intents fall back to first request tick.

## Table: variant x class
Columns: intents | lost = never got an 'applied' row | expired refusals (rows) | lost intents that also had expired refusals

| class | P intents | P lost | P expired rows | P lost w/ expired | C intents | C lost | C expired rows | C lost w/ expired |
|---|---|---|---|---|---|---|---|---|
| a healthy | 11184 | 138 | 18 | 4 | 11321 | 139 | 5 | 3 |
| b EXT fault | 2601 | 563 | 1961 | 530 | 2603 | 563 | 6 | 5 |
| c ENGINE crash | 2514 | 0 | 0 | 0 | 2487 | 0 | 0 | 0 |
| d F4 | 6182 | 34 | 5 | 0 | 6205 | 34 | 0 | 0 |
| e other (OBS/AUTH/ANCHOR) | 4479 | 77 | 22 | 1 | 4578 | 77 | 1 | 1 |
| ALL | 26960 | 812 | 2006 | 535 | 27194 | 813 | 12 | 9 |

## Q2: lost effects, SUCCESS vs not
Every lost intent (no applied row) ends non-SUCCESS in both variants (P: RECONCILED_FAILED 731, DIVERGED 74, PENDING 7; C: FAILED 735, DIVERGED 71, PENDING 7);
the lost sets are IDENTICAL: 811 intents lost in both, 1 healthy intent applied in P but not C, 0 the other way. Lost effects P 812 vs C 813; the
expired refusals add NO lost effect that conventional does not also lose. Final states of in-scope (lost or expired) intents:
- P lost: a 138 (RECONCILED_FAILED 105, DIVERGED 33), b 563 (FAILED 553, DIVERGED 8, PENDING 2), d 34 (FAILED 18, DIVERGED 11, PENDING 5), e 77 (FAILED 55, DIVERGED 22)
- C lost: a 139 (FAILED 106, DIVERGED 33), b 563 (FAILED 556, DIVERGED 5, PENDING 2), d 34 (same as P), e 77 (same as P)
- P intents with expired rows but already applied: 322 intents, 318 RECONCILED_SUCCESS, 4 DIVERGED (the same intents are applied in C).
- Crash class: 0 lost in both; P non-SUCCESS 271 vs C 161 are applied-but-state-PENDING at last observation, not expiry-related.
Lost cause of the 563/138/34/77: (b) EXT system down for the whole 8-tick window (both variants identical); (a,d,e) 'lost' intents are payload_mismatch /
target_mismatch / none refusals identical in both variants (not expiry).
Side note: 234 conventional intents (bnd-* cases: 148 crash, 86 other) have no paladin counterpart at all (applied in C, PENDING); not an expiry matter.

## Q3: Paladin's 2006 expired refusals
- 625 rows (31%) are retries of intents already applied earlier: harmless duplicates refused (a 10, b 589, d 5, e 21). 
- 1381 rows (69%) are on intents that never got an applied row (535 intents; b 1372 rows, a 8, e 1): the only attempts, issued after expiry. These intents are lost,
  but conventional loses exactly the same intents (it just never submits them).
So expiry costs Paladin 0 extra lost effects and 0 extra RECONCILED_SUCCESS; it only produces refusal noise (audit rows).

## Q4: timing
Largest gap = (b) EXT fault (1961 vs 6 rows): Paladin's due()/dispatch (extdispatch.py) never checks expiry and keeps resubmitting up to 3 times, so after the outage heals
(past commit+8) the world refuses with 'expired', whereas conventional's Outbox._eligible (extout.py) skips when now > expiry; e.g. env-000050 r004 (ERP outage ticks 2-11,
committed t=2, expiry 10): Paladin submits at t=12, 14, 17 (3 expired refusals), conventional submits nothing; both end RECONCILED_FAILED, effect never applied.

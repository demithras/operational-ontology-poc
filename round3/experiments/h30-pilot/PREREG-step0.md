# H30 pilot - step 0 pre-registration: can blast radius differ at all?

Status: EXPLORATORY (protocol/AUTHOR_DECISIONS_2026-10-16.md). No H30 verdict, no frozen threshold applies.
Written and committed before the analysis starts.

## Question
Q0. For each Gate 6 attack class in scope (A1, A2, A3, A5, A6, A7; A4 excluded per AUTHOR_DECISIONS_2026-10-15 s2) and each
blast-radius element type of PROT-H30 s1.6 (`obj:`, `ext:`, `disc:`, `prov:`), is there a concrete scenario, inside the frozen
attacker primitives (PROT-H30 s3) and the variant-neutral containment ladder L1-L6 (s4), in which BR(task, Paladin) and
BR(task, conventional) are different sets?

## Code under analysis
`round3` branch HEAD at commit time: `round3/src/paladin`, `round3/src/conventional`, `round3/src/r3_shared` (incl. the merged P1h
operator plane `opplane.py`). The WIP Gate 6 branches are read only for the G6 seams (`taint_report`) and noted separately.

## Method (static, read-only)
For every (class, element type) cell:
1. Name the code that DECIDES whether that element can enter BR in each variant (admit/deny an effect, issue/attenuate a capability,
   honour a revocation, serve a disclosure, accept a provenance record), with file:line in BOTH variants.
2. Classify the cell:
   - SHARED - the deciding code is in `r3_shared` AND both variants reach it on the same inputs (call sites cited in both).
     BR is equal by construction.
   - DIFFERENT-MECHANISM, BR-NEUTRAL - variant-specific deciding code, but no scenario makes the BR sets differ (state why).
   - CANDIDATE - variant-specific deciding code AND a concrete scenario (attacker steps, K, ladder rung) in which the sets differ;
     state the predicted direction (which variant has the larger BR) and the element(s) that differ.
   - UNKNOWN - could not be established from the code; say what is missing.
3. Pay explicit attention to the two windows where architecture can matter: (a) before detection - what capability each variant
   issues to K (attenuation granularity, derived delegations/approvals); (b) after detection - whether each ladder rung's
   revocation reaches K-DERIVED elements in each variant.

## Known-positive control (method validity)
Gate 5 recorded a real variant difference: Paladin's outbox (`extdispatch.py` due()/dispatch) resubmits expired external effects
after outages (2,019 vs 10 expired refusals) with no outcome difference (experiments/h29/exp-h29-001r3/SUMMARY.md:65,78-80).
The analysis must find this mechanism unprompted in the A7/`ext:` cell (or say why it is out of the G6 attacker model) and classify
it. If it does not surface it, step 0 is INVALID (the method is blind to variant-specific mechanisms) and is redone, not trusted.

## Orchestrator prior (written before looking)
Expected: every cell SHARED or BR-NEUTRAL (null), because every Gate 2-5 metric was at parity. Lowest-confidence cells, where a
CANDIDATE would most likely appear: A2 and A3 (capability attenuation and transitive revocation of K-derived delegations).

## Stop rule
- No CANDIDATE cell -> record "no blast-radius difference reachable under the current implementations", stop; no step 1.
- One or more CANDIDATE cells -> the orchestrator verifies each by reading the cited lines in both variants. Confirmed cells only
  go to step 1 (author's real incidents, private branch, WIP harness review first).
- Any UNKNOWN cell is resolved or listed as a limit before the stop decision is made.

# Author decisions 2026-10-16 (exploratory blast-radius pilot after H30 NOT RUN)

Context: Round 3 closed on H23-H29 with parity on every frozen gate metric (binary gates: a ceiling, not parity) and H30 NOT RUN
(AUTHOR_DECISIONS_2026-10-15 s4). The comparative question - does the Paladin composition shrink blast radius or containment cost
against the strong conventional baseline - stays open. Author chose (AskUserQuestion 2026-10-16):

1. Status: EXPLORATORY pilot, recorded under `round3/experiments/h30-pilot/`. It cannot produce an H30 verdict
   (SUPPORTED/REJECTED/INCONCLUSIVE); AUTHOR_DECISIONS_2026-10-15 s4 stays in force. A positive pilot is a reason to reopen Gate 6
   by a new author decision, nothing more.
2. Step 0 first, with a stop rule: a read-only structural analysis of whether blast radius (PROT-H30 s1.6) CAN differ between the
   variants per attack class. If no class has a concrete differentiating scenario, the pilot records the null and stops.
3. Step 1 incident source (only if step 0 finds candidate classes): real (non-public) incidents supplied or approved by the
   author, sanitised, kept off the public branch; none is used without the author's explicit approval of the sanitised text.
4. Step 1 execution: review the unmerged Gate 6 WIP branches (r3-harness 46a5151, r3-paladin 0ec5166, r3-conv 95f1b6b,
   r3-legit af66706) with known-negative and mutation checks first, then run real attacks on both variants. No hand-traced
   blast radius is reported as a measurement.
5. Step 0 found three blast-radius differences (experiments/h30-pilot/VERIFY-step0.md). Author ruling: they are BUGS TO FIX in the
   defective variant, not architectural properties; step 1 (real incidents) is not run. Erratum for M1: PROT-H24:67-68 "at the
   approval's commit point" is read as the moment the approval is CONSUMED by the approved request's commit (the stricter reading;
   conventional already did this). Result and limits: experiments/h30-pilot/RESULT.md.

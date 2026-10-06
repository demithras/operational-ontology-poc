# 09 — Python Hypothesis strategy

Property/state-machine testing is primary for H23-H29 because the dangerous failures live in combinatorial sequences:

- identity + capability + action sequences;
- delegation/revocation races;
- authority graph conflicts;
- paired secret/public worlds;
- provenance mutation combinations;
- adapter lie/retry/reorder schedules;
- fault/restart/recovery sequences.

Every major suite must include known-negative mutants and demonstrate that the suite detects them, ideally with a shrunk minimal counterexample.

H30 is different. Hypothesis may broaden frozen attack classes, but synthetic property tests alone cannot establish comparative operational value. H30 requires blind realistic tasks and a fair baseline.

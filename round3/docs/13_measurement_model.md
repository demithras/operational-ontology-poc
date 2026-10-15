# 13 — Measurement model for H30

Do not produce one weighted "security score".

Report per attack class:

- forbidden committed effects;
- blast radius: distinct protected resources/effects affected after compromise before containment;
- containment operational cost: steps and, where stable, wall-clock time to revoke/isolate and stop further harm;
- recovery cost: operator actions plus correctness of restored canonical state;
- legitimate safe-progress ratio;
- steady-state p95 latency outside attack injection;
- recurring security-specific LOC/components/configuration surface;
- regressions discovered by shared correctness/security oracles.

The primary comparison is a Pareto frontier. The preregistered H30 thresholds define a material-advantage region but do not hide trade-offs behind weights.

Zero denominators are handled explicitly: if both variants have zero forbidden effects/blast radius, that dimension is parity, not an infinite ratio advantage.

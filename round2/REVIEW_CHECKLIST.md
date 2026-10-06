# Author review checklist before protocol freeze

The hypotheses are executable-ready but **not yet preregistered**. Review these before running `make freeze`.

- [ ] Palantir-class target remains `Language × Engine × Toolchain` over `Data × Logic × Action × Security`.
- [ ] RDF remains an optional backend, not a defining requirement.
- [ ] H15 correctly treats OpenPona as a candidate, not the oracle.
- [ ] Independent IR contains every resource kind you want to test before H15 starts.
- [ ] `Function != Action` semantics are strong enough and not hiding a required effectful function use case.
- [ ] Project Ontology strong model/lifecycle is complete.
- [ ] Git authority rule is acceptable for the first self-hosting experiment.
- [ ] H18's >=25% bespoke-surface improvement threshold is acceptable before evidence reveal.
- [ ] H22's >=3 real-domain gate, 30 blind-task minimum, <=0.75 support ratios and >=0.90 reject region are acceptable.
- [ ] Baseline gets equivalent code generation/security/replay quality and is not a strawman.
- [ ] Every major property/state-machine experiment includes an injected mutation that the test must kill.
- [ ] Only after all above: run `make freeze` and commit `protocol/FREEZE.json`.

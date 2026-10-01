# 12 — Hypothesis dependency graph

The hypotheses are not a linear feature checklist. Some failures redirect rather than terminate the entire research program.

```text
H15 OpenPona Ontology Language
  ├─ survives → use OpenPona surface in later tests
  └─ rejects  → use direct typed DSL; OpenPona remains optional human/agent layer

H16 bounded kernel ───────┐
H17 Function/Action ──────┼→ H20 generic Engine → H21 Toolchain → H22 break-even
                         │
H18 Project Ontology → H19 Git authority
```

H18 depends on the Action boundary from H17. H19 depends on H18. H21 depends on a generic Engine. H22 depends on a functioning Toolchain but requires additional real domains.

## Important stop logic

- Rejecting H15 does **not** reject EOO.
- Rejecting H16 materially weakens the "bounded operational kernel" thesis.
- Rejecting H17 means the current meta-model cannot claim a hard Function/Action boundary.
- Rejecting H18 means Project Ontology dogfooding did not justify itself in the tested form.
- Rejecting H20/H21 means the system has not reached the fixed Palantir-class target even if domain workflows function.
- H22 remains inconclusive until D3+ real domains exist.

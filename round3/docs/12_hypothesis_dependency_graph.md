# 12 — Hypothesis dependency graph

```text
Round 2: H17 + H21
          │
          ▼
H23 compromised-agent effect containment
  │                         │
  ▼                         ▼
H24 delegation/revocation   H27 provenance integrity
  │                         │
  ▼                         ▼
H25 constitutional auth     H28 Byzantine adapter boundary
  │
  ▼
H26 knowledge sovereignty

H24 + H27 + H28 ───────────► H29 safe continuity/recovery

H23 + H24 + H25 + H26 + H27 + H28 + H29 ─► H30 comparative Paladin value
```

## Stop logic

- H23 rejection blocks any claim that the existing execution boundary is Paladin-safe.
- H24 rejection does not invalidate static authorization, but blocks strong delegation/revocation claims.
- H25 rejection may still leave a simpler authority kernel viable; do not rescue it with domain branches under the same hypothesis.
- H26 rejection means knowledge sovereignty is weaker than the frozen application-layer noninterference property.
- H27 rejection means provenance remains auditable but not reliably tamper-evident under the tested trust split.
- H28 rejection exposes adapters as part of the trusted computing base.
- H29 rejection means the armor harms continuity or recovery in the tested envelope.
- H30 rejection means the Paladin mechanisms may work individually but do not justify the total architectural premium in the tested regime.

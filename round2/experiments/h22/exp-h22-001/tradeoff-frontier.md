# H22 trade-off frontier (development run)

STATUS: not-run. gate closed: 2 real domains < 3 (protocol/thresholds.json H22.min_real_domains_for_verdict) and 0 blind tasks < 30; no D3+ source is registered.

No trade-off frontier can be drawn: it needs at least three real domains and 30 completed blind tasks.
This file reports no weighted winner score and no trend. Expected verdict from the preregistered domain gate: INCONCLUSIVE (domain gate).

## Context, not trend (committed single-domain facts, read from evidence)

- H15 (OpenPona vs the direct DSL, text size ratio): manufacturing lines 1.30x, project lines 1.37x; compiler LOC 1164 vs 402.
- H18 (project domain, EOO vs file-only baseline, total changed LOC ratio): TC1 5.259, TC2 3.714, TC3 3.971 (above 1 = EOO larger); H18 verdict REJECTED.
- Recurring complexity LOC: EOO 2191 vs baseline 39.
- Engine/toolchain LOC: eoo_engine 2315, eoo_engine_git 593, eoo_toolchain 757.

These are one domain / one task set each. They say nothing about how marginal cost changes with the number of domains.

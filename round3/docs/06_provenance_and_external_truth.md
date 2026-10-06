# 06 — Provenance integrity and external truth

Two different truth problems must not be conflated.

## Historical truth

H27 asks whether the system can prove what evidence, authority, policy and contract versions justified a historical decision, and detect post-hoc rewriting. Content-addressing alone is insufficient if the attacker can rewrite both data and the only stored digest; the experiment therefore requires an independent integrity anchor.

## Operational outcome truth

H28 asks whether the machine knows what actually happened outside itself. An adapter response saying "success" is an assertion, not an observation. Where a meaningfully independent observation path exists, it must corroborate the outcome; otherwise the system should remain explicit about UNKNOWN/DIVERGED confidence.

Paladin should prefer "I do not know" over a convenient but fabricated closed loop.

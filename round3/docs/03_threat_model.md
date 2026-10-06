# 03 — Threat model

The frozen machine-readable attack catalog is `threat_model/attack_classes.json`.

## Attacker assumptions

Depending on hypothesis, the attacker may fully control one agent identity, one adapter process, one mutable evidence store, or fault schedules inside the survivability envelope. The attacker may use all legitimate public calls/parameters of that boundary and may replay, reorder or race them.

The attacker is **not** automatically root on every machine and does not break cryptographic primitives. Global compromise of every independent trust root is a declared catastrophic boundary, not a case that Round 3 pretends to solve.

## Why bounded compromise matters

Security claims are meaningless if the attacker is artificially weak, but equally meaningless if the experiment grants omnipotence and then concludes no software can help. Each hypothesis freezes a concrete trust split and attacks it at the boundary the architecture claims to defend.

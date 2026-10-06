# Preregistration and freeze procedure

This pack is ready for review, not already preregistered.

Before implementation or evidence reveal:

1. review every `hypotheses/hXX/contract.json`;
2. review `threat_model/*.json` and the explicit out-of-scope boundary;
3. review `protocol/thresholds.json`, especially H29/H30 value thresholds;
4. review `baselines/FAIRNESS.md`;
5. verify `protocol/UPSTREAM_EVIDENCE.json` still pins the intended Round 2 state;
6. run `python scripts/check_pack.py`;
7. run `python scripts/freeze_protocol.py`;
8. commit the generated `protocol/FREEZE.json` before implementation/evidence generation.

Any material change after evidence reveal creates a new experiment version and new freeze. Never edit thresholds or attack-class membership in place after seeing results.

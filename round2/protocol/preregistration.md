# Preregistration and freeze procedure

This pack ships **ready to freeze**, not falsely claiming that the user's review is already a preregistered experiment.

Before implementation/reveal:

1. review every `hypotheses/hXX/contract.json`;
2. review `ontology/ir.schema.json` and semantic-equivalence rules;
3. review `protocol/thresholds.json`;
4. lock baseline fairness rules;
5. run `python scripts/check_pack.py`;
6. run `python scripts/freeze_protocol.py`;
7. commit the resulting `protocol/FREEZE.json` to Git;
8. begin implementation/experiment only from that commit.

Any material change after evidence reveal requires a new experiment version and a new freeze hash.

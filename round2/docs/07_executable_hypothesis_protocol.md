# 07 — Executable hypothesis contract

Each hypothesis directory contains a `contract.json` consumed by the common validator/evaluator.

## Required fields

```text
id
claim
null_hypothesis
rivals[]
mechanism
scope
predictions[]
falsifiers[]
experiment
oracle
baseline
required_evidence[]
evaluator
python_hypothesis_role
upstream_dependencies[]
stop_conditions[]
```

## Statuses

```text
SUPPORTED
REJECTED
INCONCLUSIVE
INVALID
```

`INVALID` is a protocol judgment, not a bad scientific result. Examples: changed thresholds after reveal, contaminated blind corpus, broken oracle, missing freeze hash.

## Support rule

Support requires all preregistered support conditions and no reject condition. It is not enough that no falsifier was observed.

## Missing evidence rule

Missing required evidence yields `INCONCLUSIVE` unless its absence itself proves protocol invalidity, in which case use `INVALID`.

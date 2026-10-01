# 08 — Evidence and fairness controls

## Machine-readable first

Authoritative results live as JSON/JSONL/CSV or deterministic test reports. Markdown reports are generated interpretations.

Each run records:

```text
experiment_id
hypothesis_id
git_commit
protocol_freeze_hash
environment
seed(s)
input corpus hash
oracle version
variant versions
raw observations
verdict
```

## Fair baseline

The conventional baseline must receive equivalent engineering quality:

- same domain requirements;
- same source data;
- same correctness oracle;
- equivalent security expectations;
- equivalent replay/audit requirements when those are part of the compared claim;
- no deliberate omission of obvious database constraints or typed schemas;
- no counting SPARQL/OpenPona/compiler glue as "free" while counting SQL/application glue.

## Blindness

Where adaptation cost is measured, freeze both variants before revealing the change/task corpus. Any benchmark-specific generic capability added after reveal is adaptation cost.

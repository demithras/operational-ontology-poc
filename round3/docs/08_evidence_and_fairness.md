# 08 — Evidence and fairness controls

## Machine-readable first

Narrative reports are views. Authoritative evidence is JSON/JSONL/CSV/test artifacts bound to the protocol freeze and candidate commit.

Every run records at least:

```text
experiment_id
hypothesis_id
git_commit
protocol_freeze_hash
environment
seed
attack_class
oracle version
candidate/baseline versions
raw observations
verdict inputs
```

## Ground truth separation

- actual effects: read from external/canonical world state, not candidate success logs;
- authority: independent procedural oracle;
- disclosure: independent low-view projection;
- provenance: independent anchor/expected binding;
- recovery: independent replay model.

## Fair baseline

See `baselines/FAIRNESS.md`. If an obvious conventional control would close the measured gap, the fair response is to add it to the baseline before freeze or invalidate/refreeze—not to celebrate a strawman win.

## Blindness for H30

Freeze both implementations and the measurement harness before revealing blind adversarial tasks. Benchmark-specific generic code added after reveal counts as adaptation effort; security bug fixes create a new candidate version and rerun.

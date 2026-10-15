# Evidence contract

Machine-readable evidence is authoritative. Every future run should record at minimum:

```text
experiment_id
hypothesis_id
git_commit
protocol_freeze_hash
environment
seed
attack_class
oracle_version
candidate_version
baseline_version (when comparative)
raw observations
verdict inputs
```

Candidate logs may be evidence inputs but may not be the sole oracle for committed effects, disclosure, authority legitimacy or external outcomes.

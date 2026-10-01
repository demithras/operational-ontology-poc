# Evidence directory contract

Do not hand-edit final verdicts here.

Recommended run layout:

```text
evidence/
  exp-0001/
    manifest.json
    H15/
      raw/...
      evidence-index.json
      verdict.json
    H16/...
```

An authoritative evidence record must identify:

- hypothesis and experiment version;
- Git commit;
- protocol freeze hash;
- environment;
- seeds/corpus hash;
- oracle version;
- candidate/baseline versions;
- raw artifact hash/path.

Markdown reports should be derived from these records.

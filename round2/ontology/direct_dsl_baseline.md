# Direct typed DSL baseline for H15

The language baseline is intentionally boring: JSON/YAML objects that map directly to the frozen IR fields.

Its purpose is not usability aesthetics. It answers:

> If a direct typed representation already expresses the IR unambiguously, what semantic compression or operational benefit does OpenPona provide, and what ambiguity/cost does it add?

The baseline receives the same:

- IR schema;
- semantic-equivalence oracle;
- real-domain corpus;
- generated valid/invalid cases;
- type/cardinality/authority/version tests.

It may use aliases/macros only if those are frozen before reveal and their implementation cost is counted.

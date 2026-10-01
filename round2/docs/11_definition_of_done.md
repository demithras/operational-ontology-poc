# 11 — Definition of done for the pack

The pack is ready for implementation when:

- all H15-H22 contracts validate;
- independent IR schema parses;
- thresholds/structural support conditions are explicit;
- no hypothesis relies on narrative-only evidence;
- evaluator missing-evidence behavior is tested;
- protocol can be frozen by hash;
- mutation requirements are declared for H15-H21;
- OpenPona and baseline DSL are judged against the same IR oracle;
- Git authority rules are explicit;
- H22 cannot accidentally become SUPPORTED with fewer than three real domains.

The implementation round is done only when every active hypothesis has an authoritative verdict or an explicit dependency-based stop.

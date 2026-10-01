# H15 report: exp-h15-001

Generated from the evidence JSON by `scripts/evaluate_h15.py`; `verdict.json` and the six evidence files are the authority, this file is a view.

**Verdict: SUPPORTED**

```
{
 "protocol_valid": true,
 "required_evidence_complete": true,
 "sample_sufficient": true,
 "reject_hit": false,
 "support_hit": true
}
```

## support_if

| id | clause | holds |
|---|---|---|
| S1 | 100% of frozen real-domain contracts are semantically equivalent after OpenPona round-trip | True |
| S2 | 0 semantic-equivalence failures across at least 10,000 generated valid cases | True |
| S3 | 0 required new primitive tokens | True |
| S4 | 0 indispensable semantic sidecar fields | True |
| S5 | 100% of predeclared ambiguity/missing-type cases fail closed or remain unresolved | True |
| S6 | All target mutation classes are detected | True |

## reject_if

| id | clause | holds |
|---|---|---|
| R1 | Any falsifier is observed in a frozen real-domain contract | False |
| R2 | Any generated minimal counterexample demonstrates irreversible semantic loss in a required IR kind | False |
| R3 | A new primitive token or indispensable semantic sidecar is required | False |
| R4 | The compiler resolves an ambiguous input by silently inventing semantics (falsifier 5; mapped to reject) | False |

## inconclusive_if

| id | clause | holds |
|---|---|---|
| I1 | Generated coverage is below 10,000 valid cases | False |
| I2 | Either registered domain is not encoded completely | False |

## invalid_if

| id | clause | holds |
|---|---|---|
| V1 | Evidence records carry a protocol / Gate-0 / candidate hash different from the frozen files | False |
| V2 | Evidence records disagree on commit / seed / corpus hash | False |
| V3 | Harness self-check failed (mutation control not clean, oracle known-negative missed, patches leaked) | False |

## Real domains

| domain | resources | OpenPona equivalent | OpenPona complete | DSL equivalent |
|---|---|---|---|---|
| manufacturing | 111 | True | True | True |
| project | 93 | True | True | True |

## Generated corpus

valid cases 10000 (unique 9789), corpus 84733ec78b70e5f7

| surface | ok | failed | unrepresentable | exact | render ms | compile ms |
|---|---|---|---|---|---|---|
| dsl | 10000 | 0 | 0 | 10000 | 0.20 | 3.85 |
| openpona | 10000 | 0 | 0 | 10000 | 1.51 | 5.84 |

## Ambiguity

| surface | declared | fail closed | accepted | deletion mutants | raised | accepted exact | violations |
|---|---|---|---|---|---|---|---|
| dsl | 39 | 39 | 0 | 900 | 653 | 247 | 0 |
| openpona | 44 | 44 | 0 | 3280 | 2557 | 723 | 0 |

## Sidecar audit

indispensable sidecar count 0; findings 0; generated sample 2000 packages: alpha failures 0, shape failures 0, reference slots 39544 of which via coreference labels 39544.

| domain | alpha ok | shape ok | reference slots | via labels |
|---|---|---|---|---|
| manufacturing | True | True | 181 | 181 |
| project | True | True | 204 | 204 |

## Mutation

| mutant | kind | killed | hits |
|---|---|---|---|
| openpona:drop_cardinality | target | True | {"valid_input_rejected": 40} |
| openpona:swap_function_action | target | True | {"valid_input_rejected": 52} |
| openpona:drop_authority_ref | target | True | {"deletion_mutant_invented": 20, "non_equivalent": 23} |
| openpona:drop_version | target | True | {"valid_input_rejected": 65} |
| openpona:accept_ambiguous_binding | target | True | {"ambiguity_case_accepted": 3} |
| openpona:default_missing_type | target | True | {"ambiguity_case_accepted": 2, "deletion_mutant_invented": 6} |
| openpona:default_immutable_false | extra | True | {"deletion_mutant_invented": 54} |
| openpona:accept_parse_ambiguity | extra | False | {} |
| dsl:drop_cardinality | target | True | {"deletion_mutant_invented": 23, "non_equivalent": 40} |
| dsl:swap_function_action | target | True | {"deletion_mutant_invented": 69, "non_equivalent": 52} |
| dsl:drop_authority_ref | target | True | {"deletion_mutant_invented": 25, "non_equivalent": 23} |
| dsl:drop_version | target | True | {"deletion_mutant_invented": 78, "non_equivalent": 65} |
| dsl:accept_ambiguous_binding | target | True | {"ambiguity_case_accepted": 2} |
| dsl:default_missing_type | target | True | {"ambiguity_case_accepted": 1, "deletion_mutant_invented": 10} |
| dsl:default_required_false | extra | True | {"ambiguity_case_accepted": 1, "crash": 1, "deletion_mutant_invented": 11} |

controls clean: {dsl: True, openpona: True}

## Metrics

compiler+renderer LOC: OpenPona 1164, DSL 402; rules: 92 line templates vs DSL field table 83; gap constructs 0; new primitive tokens 0.

| domain | resources | OP bytes | DSL bytes | OP lines | DSL lines | OP tokens | DSL tokens |
|---|---|---|---|---|---|---|---|
| manufacturing | 111 | 67629 | 40798 | 1864 | 1437 | 17845 | 6376 |
| project | 93 | 45094 | 27059 | 1262 | 924 | 12339 | 4644 |

## Interpretation notes

- R4 maps falsifier 5 (silent invention of semantics) to reject; the contract's reject_if list names only R1-R3.
- Mutation kill rate is judged on target classes for BOTH compilers; extra mutants are informational.
- The DSL baseline numbers are reported but only OpenPona enters S1-S5.

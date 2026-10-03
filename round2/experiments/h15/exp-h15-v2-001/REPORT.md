# H15 report: exp-h15-v2-001

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

## Problems

```
{
 "problems": [],
 "protocol": {
  "records_with_wrong_hashes": [],
  "disagreeing_provenance": false,
  "harness_self_check": [],
  "v2_candidate_pin": {
   "path": "/private/tmp/claude-501/-Users-d-surchis-work-operational-ontology-poc/83ecb957-a4bb-430b-84f3-5b83562a7f31/scratchpad/wt-r15v2/round2/protocol/H15_V2_CANDIDATE.json",
   "present": true,
   "combined_sha256": "e9b057c1b9366b2737a4e76dcdf765d5be16e971b8c9dae4fae76ffd55a297e0",
   "h15_v2_prereg_sha256": "1822dad087651d81da3dfd4749021dbaf9d9e83d44536c9c76f9d1698fbc932b"
  }
 }
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

valid cases 10400 (unique 10175), corpus 14cfed5e7dfff930

| surface | ok | failed | unrepresentable | exact | render ms | compile ms |
|---|---|---|---|---|---|---|
| dsl | 10400 | 0 | 0 | 10400 | 0.28 | 5.31 |
| openpona | 10400 | 0 | 0 | 10400 | 2.07 | 3.12 |

## Ambiguity

| surface | declared | fail closed | accepted | deletion mutants | raised | accepted exact | violations |
|---|---|---|---|---|---|---|---|
| dsl | 39 | 39 | 0 | 900 | 651 | 249 | 0 |
| openpona | 49 | 49 | 0 | 3198 | 2299 | 899 | 0 |

## Sidecar audit

indispensable sidecar count 0; findings 0; generated sample 2000 packages: alpha failures 0, shape failures 0, reference slots 39544 of which via coreference labels 0.

| domain | alpha ok | shape ok | reference slots | via labels |
|---|---|---|---|---|
| manufacturing | True | True | 181 | 0 |
| project | True | True | 204 | 0 |

## Mutation

| mutant | kind | killed | hits |
|---|---|---|---|
| openpona:drop_cardinality | target | True | {"valid_input_rejected": 40} |
| openpona:swap_function_action | target | True | {"valid_input_rejected": 52} |
| openpona:drop_authority_ref | target | True | {"deletion_mutant_invented": 20, "non_equivalent": 23} |
| openpona:drop_version | target | True | {"valid_input_rejected": 65} |
| openpona:accept_ambiguous_binding | target | True | {"ambiguity_case_accepted": 1} |
| openpona:default_missing_type | target | True | {"ambiguity_case_accepted": 2, "deletion_mutant_invented": 5} |
| openpona:default_immutable_false | extra | True | {"deletion_mutant_invented": 63} |
| openpona:accept_parse_ambiguity | extra | False | {} |
| openpona:auto_close_metadata | extra | True | {"ambiguity_case_accepted": 1} |
| dsl:drop_cardinality | target | True | {"deletion_mutant_invented": 23, "non_equivalent": 40} |
| dsl:swap_function_action | target | True | {"deletion_mutant_invented": 69, "non_equivalent": 52} |
| dsl:drop_authority_ref | target | True | {"deletion_mutant_invented": 25, "non_equivalent": 23} |
| dsl:drop_version | target | True | {"deletion_mutant_invented": 78, "non_equivalent": 65} |
| dsl:accept_ambiguous_binding | target | True | {"ambiguity_case_accepted": 2} |
| dsl:default_missing_type | target | True | {"ambiguity_case_accepted": 1, "deletion_mutant_invented": 10} |
| dsl:default_required_false | extra | True | {"ambiguity_case_accepted": 1, "crash": 1, "deletion_mutant_invented": 11} |

controls clean: {dsl: True, openpona: True}

## Metrics

compiler+renderer LOC: OpenPona 1267, DSL 402; rules: 93 line templates vs DSL field table 83; gap constructs 0; new primitive tokens 0.

| domain | resources | OP bytes | DSL bytes | OP lines | DSL lines | OP tokens | DSL tokens |
|---|---|---|---|---|---|---|---|
| manufacturing | 111 | 118682 | 40798 | 3811 | 1437 | 36196 | 6376 |
| project | 93 | 70687 | 27059 | 2420 | 924 | 22963 | 4644 |

## Meaning rule (H15 v2 bounded-vocabulary test)

bounded: 259 distinct phrases over 2002 packages (phrase table 259); sizes over the bound: none.

| size | packages | mean distinct | max distinct | distinct in group | cumulative |
|---|---|---|---|---|---|
| 0 | 9 | 2.44 | 3 | 5 | 5 |
| 1 | 24 | 8.42 | 13 | 65 | 66 |
| 2 | 39 | 12.74 | 21 | 102 | 116 |
| 3 | 58 | 17.84 | 31 | 161 | 172 |
| 4 | 62 | 24.55 | 44 | 183 | 204 |
| 5 | 86 | 29.77 | 56 | 210 | 229 |
| 6 | 116 | 34.26 | 62 | 218 | 244 |
| 7 | 122 | 40.7 | 71 | 229 | 253 |
| 8 | 128 | 45.47 | 69 | 237 | 257 |
| 9 | 153 | 51.12 | 81 | 241 | 258 |
| 10 | 151 | 56.01 | 90 | 246 | 259 |
| 11 | 162 | 61.42 | 87 | 253 | 259 |
| 12 | 158 | 66.53 | 88 | 249 | 259 |
| 13 | 148 | 71.74 | 105 | 244 | 259 |
| 14 | 148 | 75.9 | 105 | 243 | 259 |
| 15 | 131 | 77.16 | 103 | 242 | 259 |
| 16 | 106 | 82.43 | 114 | 244 | 259 |
| 17 | 73 | 86.27 | 121 | 230 | 259 |
| 18 | 56 | 90.18 | 116 | 228 | 259 |
| 19 | 26 | 93.69 | 115 | 210 | 259 |
| 20 | 18 | 97.11 | 115 | 211 | 259 |
| 21 | 13 | 97.85 | 110 | 187 | 259 |
| 22 | 9 | 105.22 | 125 | 172 | 259 |
| 23 | 4 | 103.5 | 115 | 153 | 259 |
| 93 | 1 | 98.0 | 98 | 98 | 259 |
| 111 | 1 | 100.0 | 100 | 100 | 259 |

## Interpretation notes

- R4 maps falsifier 5 (silent invention of semantics) to reject; the contract's reject_if list names only R1-R3.
- Mutation kill rate is judged on target classes for BOTH compilers; extra mutants are informational.
- The DSL baseline numbers are reported but only OpenPona enters S1-S5.
- H15 v2 (protocol/H15_V2_PREREG.json): V1 checks the v2 candidate pin and the v2 prereg hash.
- Meaning rule (bounded vocabulary) enters R3 (reject) and S4 (support); unknown meaning-rule result keeps R3/S4 unknown.

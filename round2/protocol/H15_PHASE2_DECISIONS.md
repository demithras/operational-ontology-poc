# H15 Phase 2 — orchestrator rulings on the OpenPona surface (before the frozen run)

Made 2026-10-01, before Phase 3 (the 10,000-case run). FREEZE.json and H15_GATE0.json unchanged.

| # | Question raised by the Phase 2 builder | Ruling |
|---|---|---|
| 1 | Addresses `<head> pi X Y` are enumerated coreference labels with no gloss content. Cipher under R4? | **Allowed.** R4 (orchestrator brief rule, not frozen protocol) forbids encoding *values* — enum members, integers, bits — by arbitrary tokens. These labels encode identity only: any bijective renaming compiles to the identical IR (tested; orchestrator probe: renaming every non-numeric atom re-renders to the identical text). Because a stricter reader could rule otherwise, Phase 3 MUST report the number of IR reference slots carried by coreference labels, so the alternative reading can be applied to the same evidence without rerunning. |
| 2 | Weak glosses: `number` = `kulupu pilin`, `date` = `tenpo sike`, `git_change` = `sitelen`, metadata floats | Not gaps: each has a canon-gloss justification and is distinguishable. Recorded as language-adequacy weaknesses for the report; they do not enter the frozen verdict, which measures lossless compilation. |
| 3 | Sequence order = line order; duplicates = repeated lines | Allowed; every text surface (including the DSL baseline) writes lists this way. |
| 4 | canon/05 keeps `bound_ref` in the record | Superseded for H15 by the frozen contract: the reference graph must be in the line. Hence ruling 1. |
| 5 | `metadata` is not listed in `sidecar_classification` | Metadata keys and scalar values are atoms; JSON shape (object/array/scalar kind) is structure and is in the line (`meta.*` rules). |
| 6 | Constant-placeholder line-only test collapses identifiers | Phase 3's line-only shape test uses a UNIQUE placeholder per record slot, kind-valid (numeric slots get "1"). |

Orchestrator verification of Phase 2: verify script re-run; OpenPona installed at 97a9b9e (direct_url.json);
2,231/2,231 domain lines parse RESOLVED; 0 non-neutral record keys; 0 META repetitions; exact round trip
both domains; deleting the first line of each of 6 critical rules (type, required, purity, authority effect,
cardinality max, policy decision) is rejected; Function line relabelled with an Action head is rejected;
alpha-renaming of atoms re-renders to the identical text.

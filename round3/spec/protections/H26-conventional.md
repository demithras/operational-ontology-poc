# H26 protections - conventional variant (knowledge sovereignty on low channels, PROT-H26)

Paths relative to `round3/src/conventional/`; line numbers at the commit tagged `r3-g3-conventional`. Sovereignty is
implemented HERE (author decision 2: no shared visibility helper); only forms and `tool_schema` come from `r3_shared`.
Architecture (EQUIVALENCE-G3 'conventional'): the v3 `disclosure` document is policy data; ONE read-side authorization
filter, `lowview.py` (`ViewBuilder.build` -> `LowView`), turns (world, authority document, observer, tick) into the
observer's low view; EVERY low channel is a projection of that view. There is no per-endpoint trimming.

| Id | Where | Mechanism |
|---|---|---|
| Low view (s2) | `lowview.py:102` (`build`), `lowview.py:80` (`_reveal`), `lowview.py:141` (`_act_implies`) | Least fixpoint: public types + act-implies-exists (base/edge authority via the PDP, world-independent) + non-via rules with `exists`, then via rules through already-visible objects; deny overrides allow; fields/links/provenance follow covering rules; hidden fields ABSENT. |
| Hidden == absent (R26-2) | `lowreads.py:44` (`read_object`), `:53`, `:60`, `:70`; `lowprov.py:57`, `:86`, `:99`; `lowevents.py:49`; `govsvc.py:92` (`_case` -> `unknown_case`); `authdoc.py` `edge_visible` + `authority_ops.py` (`unknown_parent`/`unknown_edge`) | Visibility is asked once (`LowView.has` / `edge_visible` / `_sees`); a miss returns the same constant as a nonexistent key (`NOT_FOUND`, `UNKNOWN`, `BAD_SUB`). A bad token is an observer who sees nothing. |
| Check order (3.2) | `service.py:296-326` (`_execute`: token -> schema -> hidden/coarse authority), `service.py:367-382` (`_txn`: PDP decision, `case_required`, then existence/preconditions/rules/approvals) | schema before authority before any world read; refusals decided before existence carry no world fact. |
| Uniform errors (3.6) | all refusal bodies are `{reason[, rule\|input]}`; `service.py` detail fields removed; `variant.py` `_safe` | no exception text, no values. |
| Queries (3.3) | `lowreads.py:70` (`query`) | helpers run over a `WorldView` built from the LOW objects/links. |
| Tools (3.4) | `tools.py:16-30` | `tool_schema(op_def)` verbatim; names = PDP upper bound (delegators, edges) + ACTIVE-emergency scope ops (`govsvc.py:301`). |
| Subscriptions (3.5) | `lowevents.py:49-112` | `poll` replays committed world_log transactions on a private copy, builds the observer's view before/after each, emits only changed low projections in the frozen event form; ids `sub-<principal>-<n>` (deterministic). |
| Provenance (s4) | `lowprov.py:31` (`_decision_low`), `:57` (`prov_decision`), `:99` (`authority_used_as`) | decisions are low iff OWN or all resource inputs visible at provenance >= scalars (edge decisions: edge visible); actors/args/effect fields are TRUE or an explicit marker (`r3_shared.disclosure.marker`); `partial` is constant; chain fields are never returned. Index records `decidx/` are written by `provenance.py` `_index`. |
| Determinism (s5) | `lowevents.py` ids; no uuid/time/id() in any new module | A/A control = `test_r26_5_determinism_a_a_control`. |

## Decision rules where the frozen text needed an interpretation (reported)
1. Deny rules: `exists:true` hides the object, listed fields/links are removed, a non-`none` `provenance` zeroes provenance (the frozen text does not define deny `reveals`).
2. `args_digest` of a non-own decision is true only when the args consist solely of visible resource keys; `effect_digest` only for own decisions; `subject`/`on_behalf_of` true only at `actors` level or own (else the `actor` marker, even when the truth is null).
3. Act-implies-exists probes one resource (T:k) per operation input of that type; edge roots are the issuers of edges whose child is the observer.
4. A bad token on read_object/list_objects/prov_*/authority_used_as behaves as an empty observer (frozen refusal forms); on subscribe/poll/query/list_links it is DENIED `invalid_token`.
5. A duplicate edge id colliding with a hidden edge still answers `duplicate_edge` (edge ids are global in the document).

## Mutant sites
| Mutant | Site | Bug |
|---|---|---|
| `existence_status_split` | `lowreads.py:41-48` | hidden-but-existing -> DENIED `forbidden`, absent -> INVALID `not_found`. |
| `error_detail_leak` | `service.py:247` (`_leak_detail`) | refusal body gains `detail` with the resource objects' values. |
| `hidden_tool_schema` | `tools.py:20-21` | tools() lists every operation regardless of the subject. |
| `provenance_edge_retained` | `lowprov.py:42`, `:52`, `:111` | hidden edge ids, actors and the authority version returned unredacted. |
| `subscription_unfiltered` | `lowevents.py:78`, `:93` | poll delivers every committed change with true values. |
| `redaction_fabrication` | `lowprov.py:49`, `:55` | redacted actors/edges replaced by the string `system`, no marker. |

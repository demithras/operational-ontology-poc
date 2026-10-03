# Author decisions on the two orchestrator rulings (2026-10-03)

Made by the pack author after all H15-H22 results were reported. Both are recorded as post-reveal decisions;
no committed evidence file is edited.

## 1. H15 — coreference labels (overrides protocol/H15_PHASE2_DECISIONS.md ruling 1)

Author: "Ids of concrete records are metadata and live outside the language. Every combination of OpenPona words
must have a meaning. Labels without meaning must not exist."

Consequences:
- exp-h15-002 (SUPPORTED as evaluated) does not stand: its lossless round trip relies on enumerated `<head> pi X Y`
  labels with no gloss content for 100% of reference slots (181/181 manufacturing, 204/204 project). Under the
  author's rule that encoding is not valid OpenPona. **H15 as tested (candidate at tag r2-h15-openpona): REJECTED.**
- The same decision clarifies the sidecar boundary: identifiers (including the id a reference points to) are
  record metadata. That makes a different encoding legitimate (a meaningful phrase such as `ijo ni` bound to the
  target id in the record). It was excluded by the orchestrator's earlier reading of option 1 ("the reference
  graph must be in the line") and has not been tested. Testing it requires a new experiment version (H15 v2) with
  this amended boundary frozen first.

## 2. H20 — Git commit trailers written by the adapter (replaces protocol/H20_RULINGS.md ruling 1)

Author chose the orchestrator's third option: remove the question instead of ruling on it. The Engine composes the
provenance envelope for every effect; adapters may only write it verbatim. Engine v1.2; the H20 adapter audit runs
with no declared exceptions; H17, H20 and H21 are re-run on v1.2 as new experiment versions in isolated worktrees.
exp-h20-001 / exp-h21-001 / exp-h17-003 stay on record as results for Engine v1.1.

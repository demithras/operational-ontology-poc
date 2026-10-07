# Post-hoc verification note (orchestrator, 2026-10-07) - evidence files unchanged

Found during Gate 2 (H24 harness builder; confirmed by the orchestrator): in the H23 runner,
`ROUND3 = Path(__file__).resolve().parents[3].parent` points at the repository root instead of `round3/`. Consequences
for this run (candidate commit 01bc7ac):
1. The in-run oracle-independence check (`oracle_independent()`) scanned no files and could not fail.
2. `candidate_version` in each `envelope.json` is the sha256 of empty input (`e3b0c442...`) and does not identify code;
   `git_commit` is correct and identifies the candidate exactly.

Independent re-check of the property the contract's invalid_if clause requires ("the authority oracle imports candidate
enforcement code"): an AST scan of every `round3/src/r3_oracle/*.py` file at commit 01bc7ac (via `git show`, 10 files) finds
0 imports of `paladin`, `conventional` or `r3_harness`. The separately enforced `tests/test_import_boundaries.py`
(proven on a known-negative) also passes. The invalid_if condition is therefore false and the recorded verdict stands.
The runner bug is fixed going forward (Gate 2 integration), with a known-negative test that the scan is non-vacuous.

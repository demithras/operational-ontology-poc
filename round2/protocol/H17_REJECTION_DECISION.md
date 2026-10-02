# H17 exp-h17-001 REJECTED — how the kill-chain proceeds (orchestrator decision, 2026-10-02)

**Fact.** exp-h17-001 (commit 91455df) is REJECTED: Engine v1 (tag r2-engine-core) returned its live execution
record to callers; editing that record turned gate-denied requests into executed effects (reject clause R2).
That verdict stands permanently for Engine v1.

**Decision.** The defect is an implementation flaw (object aliasing + a recovery path that trusts mutable
state), not evidence that a hard Function/Action boundary is impossible in this meta-model. The thesis is
unchanged. The Engine is therefore fixed as a NEW CANDIDATE VERSION (v1.1) and H17 is re-run as a NEW EXPERIMENT
VERSION (exp-h17-002) with the UNCHANGED exp-h17-001 harness, contract, thresholds and evaluator. Downstream
hypotheses (H18-H22) run on Engine v1.1 and every verdict names the Engine version.

**What does not change.** FREEZE.json, ENGINE_PREREG.json, the H17 contract/thresholds, the H17 harness and its
attack catalogue, the oracle. The fix may not weaken any gate. If exp-h17-002 hits any falsifier, H17 is REJECTED
again and the chain stops by dependency.

**Strict alternative (recorded for the author).** Reading AGENTS.md literally ("a rejected hypothesis narrows or
stops downstream work unless a new version explicitly changes the thesis"), H18-H22 would end here as
dependency stops. The author may adopt that reading; exp-h17-001 alone supports it.

# PROT-H23 addendum: A8 crash, restart and concurrency (both variants) - binding before the official H23 run

Why: the frozen H23 contract lists "replay, retry, crash and stale decisions" among its experiment steps and makes A8
coverage an INCONCLUSIVE condition. Sequential replay alone does not cover A8.

R5 (clarified): a request_id that has committed never produces a second effect - INCLUDING after crash() + restart().
R9 crash safety: a crash at either armed point leaves the world in a state the oracle accepts: before_commit -> zero effects
   from that request; after_commit -> exactly that request's effects. After restart(), re-sending the same request (same
   request_id) yields no additional effect; re-sending it with a NEW request_id is a new request decided against current
   authority and preconditions.
R10 concurrency safety: concurrent callers on one Deployment never create a forbidden effect, never commit the same
   request_id twice, and the final world equals the oracle's final world for SOME serial order of the concurrent requests.
   Refusing a concurrent legitimate request with UNAVAILABLE is safe but is counted as lost progress (measured).

Protocol (r3_shared.variant, shared commit P1c):
- `Variant.deploy(..., state_dir: str | None = None)`: a private directory that survives crash/restart; the world store
  also survives. Everything in memory is lost on crash.
- `Deployment.arm_crash(point: Literal["before_commit", "after_commit"]) -> None`: the NEXT mutating request (call_tool,
  direct, approve) crashes at that point: before_commit = after authorization/validation, before any world write;
  after_commit = after the world commit, before the result is returned or any post-commit bookkeeping. The call returns
  CallResult("UNKNOWN", {"reason": "crashed"}); afterwards every call returns UNAVAILABLE {"reason": "crashed"} until restart().
- `Deployment.crash()` crashes immediately (between requests); `Deployment.restart()` rebuilds from the world store +
  state_dir only.
- Thread safety: call_tool/direct/approve/read may be called concurrently from threads.
- Mutants (KNOWN["H23"] gains): "ledger_after_commit_volatile" (the committed-request record is kept only in memory /
  written after acknowledging, so a crash at after_commit + replay double-commits) and "unsynchronized_commit"
  (the authorize->commit section runs without the variant's concurrency control).

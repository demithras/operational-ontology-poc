# exp-h23-001 - attribution of the REJECTED verdicts (orchestrator, 2026-10-07)

Official run: candidate `r3-h23-candidate` (01bc7ac), isolated worktree, seed 2310, 10,000 unique sequences per variant,
300 concurrency scenarios, mutation proof. `verdict.json` is unedited: **paladin REJECTED, conventional REJECTED**
(`forbidden=3 identity_expansions=0 backstop_failures=1` for both). `minimum_overrides` is empty. The two
`adversarial-sequences.jsonl` files are stored gzip-compressed; `RAW_SHA256.txt` holds the hashes of the uncompressed files.

## What was flagged

All 4 flags (3 forbidden effects + 1 backstop failure, identical in both variants; the variant differential shows 0
differing calls of 96,504) share one cause. Sequences 2310-3728, 2310-3804, 2310-5120 (manufacturing):

1. a legitimate approver (`senior-1`) pre-approves a `transfer_inventory` above the 80-unit threshold for a requester
   that is a delegate of `planner-1` (`agent-1` or `agent-hostile-1`), with `on_behalf_of` either null or `planner-1`;
2. the `appr_swap` rule then commits different inputs, so that approval stays unconsumed;
3. a later step commits exactly the approved inputs with the *other* `on_behalf_of` form;
4. both variants treat the two forms as one request and consume the approval; the oracle compares `on_behalf_of`
   literally, predicts `NEEDS_APPROVAL`, and classifies the committed transfer as a forbidden effect (via `direct` in
   2310-5120, hence also a backstop failure).

## Why the oracle and the variants disagree

The pre-run specification was contradictory, through an orchestrator error:
- P1b protocol (`src/r3_shared/variant.py`, approve docstring): an approval binds "the EXACT request (requester,
  on_behalf_of, operation, args canonicalised)". The oracle implemented this.
- The orchestrator's P2a rework brief (2026-10-06, before this run) told the Paladin builder: "A delegate's request with
  and without on_behalf_of=<its delegator> is the same request", and accepted the same reading from the conventional
  builder, without amending the protocol text or the oracle.

No principal obtained an effect that a legitimate approver had not approved for that same requester and inputs; the
disagreement is about whether the `on_behalf_of` field is part of the approval binding.

## Author decision (2026-10-07)

The verdict stands as recorded. The oracle is not changed. Both variants are tightened to the protocol text (an approval
binds `on_behalf_of` exactly as supplied) in a new candidate version, measured as exp-h23-002 with a new seed
(pack rule: "fix it only in a new candidate experiment version rather than weakening the oracle").

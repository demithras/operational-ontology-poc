# Gate 2 equivalence plan - Paladin mechanism vs strongest conventional equivalent

DRAFT g2-design (2026-10-07). Input for protocol/HARDENING_LEDGER.jsonl rows and the pre-gate equivalence audit.
Shared (both variants, same code): world store + world_log + writer allowlist, LogicalClock, auth-spec v2 schema and
validate_strict, scope helpers (optional use), HistoryStore, AnchorClient + anchor process, canonical_bytes/sha256.

## H24

| Protection | Paladin-shaped mechanism (expected) | Strongest conventional equivalent | Fairness risk |
|---|---|---|---|
| Edge model + attenuation (R24-1) | Capabilities compiled into the IR/Engine as version-bound capability objects; Engine authority rule computes path intersection | Central PDP with a versioned delegation table (Zanzibar/ReBAC-style relation tuples with caveats for scope/expiry); subset check at issuance in the delegation service, intersection at decision | Low if both read the same v2 doc. Risk: Paladin recompiles the IR per delegate (latency), conventional updates a table - a latency gap is architecture, report it, do not "fix" it in one variant only |
| Freshness at commit (R24-2/3) | Authority check re-run inside the Engine commit pipeline under the world transaction (tx.tick, tx order) | Same: PDP decision re-evaluated inside the service's commit transaction against the current table version (no token-embedded authority trusted at commit) | HIGH: the conventional "short-lived token" baseline (contract text) is weaker if it trusts token scope until expiry. The FAIR conventional design is token for identity + PDP check at commit; the ledger row must say tokens never carry authority. Do not build a strawman JWT-scope variant |
| Revocation durability (R24-5) | Engine authority log in HistoryStore/state_dir, written before ack | Delegation table in its own durable store, revocation committed in the world tx (mark) before ack | Low |
| Cycle/conflict explicit (R24-4) | IR validation + Engine path rule | Validation in delegation service + validate_strict | Low; both call validate_strict for set_authority, own checks for runtime delegate |
| Historical authority (R24-6) | Engine records version + path in its provenance envelope | Decision log row (version, path) per request | Low |
| Safe progress (R24-7) | Engine serialises commits; revocation is one tx | Service serialises commits per world tx | Medium: whichever variant holds a global lock across a slow PDP/compile step loses progress under races; that is a real measured difference, keep it |
| Caching | Compiled-IR cache keyed by authority version | PDP decision cache keyed by table version | HIGH for stale_authority_cache mutant parity: both must place the cache where a real one would live (keyed by version, invalidated on mark). The auditor checks the mutant sits in the real cache in both, not in a test-only branch |

## H27

| Protection | Paladin-shaped mechanism | Strongest conventional equivalent | Fairness risk |
|---|---|---|---|
| Envelope + content addressing | Engine ProvenanceEnvelope (Round 2 H19 lineage) extended to PROT-H27 s2 fields; IR artifacts (policy/contract) are already content-addressed | Append-only audit log (event store) with content-addressed artifact table (sha256 keys), envelope per decision in the same frozen format | Low: the envelope FORMAT is frozen and shared, so the difference is who computes it (Engine vs service middleware) |
| Chain + anchor before ack | Engine appends root to AnchorClient inside the decision path | Audit-log writer appends root to the SAME AnchorClient before the API returns | None: same anchor class (author decision #4); auditor checks both call append before returning |
| Replay without fallback | Engine replays from IR artifacts by digest | Replay service resolves artifacts by digest from the artifact table, refuses on miss | Medium: conventional code often "helpfully" loads current config; the ledger row must point to the refusal line |
| Continuation (R27-5) | Engine checks idempotency/approval records against anchor lookup on restart | Service checks idempotency/approval rows against anchor lookup | HIGH migration cost for BOTH (records move into HistoryStore); give both builders the same brief and the same migration budget |
| Trust split | Same anchor process, same sandbox, same HistoryStore | Same | None by construction; the risk is a variant keeping a private untampered copy (state_dir) - prevented by fresh-deploy replay with empty state_dir |

## Where Paladin advantage could be fabricated (auditor checklist)
1. Conventional given a token-scoped authority design instead of commit-time PDP (strawman) - block.
2. Paladin's Round 2 provenance envelope counted as "free" while conventional middleware LOC is counted - count both
   (FAIRNESS.md: no free candidate glue).
3. Tamper corpus discovering artifacts via a layout one variant declares more completely - content discovery first.
4. Different HistoryStore usage (e.g. one variant stores approvals in world aux tables, outside the attacked store) -
   P1d-4 requires all durable records in HistoryStore when `history` is given; auditor greps for other sqlite/state files.
5. Latency compared on a contended host - p95 is descriptive only (as exp-h23-002).

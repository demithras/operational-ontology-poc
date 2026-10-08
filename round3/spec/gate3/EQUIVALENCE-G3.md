# Gate 3 equivalence plan - Paladin mechanism vs strongest conventional equivalent

FROZEN 2026-10-08 (author decisions 2026-10-08; rulings in spec/gate3/OPEN-QUESTIONS.md). Input for protocol/HARDENING_LEDGER.jsonl rows and the pre-gate equivalence audit.
Shared (both variants, same code): governance schema + validate_governance + structural_signature (P1e-1), auth-spec v3
schema + validate_strict, tool_schema derivation (P1e-5), world store + world_log + seed(), clock, HistoryStore,
AnchorClient, canonical_bytes. NOT shared: procedural evaluation, visibility/redaction (each variant builds its own;
the oracle has a third, independent one).

## H25

| Protection | Paladin-shaped mechanism (expected) | Strongest conventional equivalent | Fairness risk |
|---|---|---|---|
| Governance as data (R25-6) | Governance document compiled into IR authority primitives (bodies, matters, precedence as typed relations); one Engine rule evaluates every model | Generic policy decision point (Cedar/OPA/Zanzibar style) loading the same document as policy data + a small procedure service (cases, judgments) with a generic evaluator | HIGH: the contract's rival lets the baseline use "domain policy modules". FAIR reading (Q1): modules as DATA are allowed for both; per-domain CODE branches count against both. Do not give conventional hand-written per-model handlers and then fail it on the audit |
| Procedure state (cases, judgments, appeals) | Engine records actions as commit-ordered facts (marks) and derives outcomes on read | Case table + judgment table written in the same world tx as the mark; outcomes derived by the PDP at execute | Low: the mark is frozen and shared; difference is where derivation lives |
| Quorum/recusal/precedence/review | Generic IR rules | Generic functions in the PDP over the same document | Low; C25-2/C25-3 force identical order and mark bytes |
| No fabricated merit (R25-3) | Engine has no merit vocabulary; judgments are opaque facts | Procedure service treats merit as an opaque column | Medium: conventional code often adds "default approve after timeout"; only a document-declared lapse is legal. Auditor greps both for timeout defaults outside lapse handling |
| Bounded emergency (R25-4) | Emergency as a scoped, expiring capability object in the IR; checked at commit | Emergency grant row with scope + expires_at, checked by the PDP inside the commit tx | Low; the HIGH risk is a token-embedded emergency claim (trusted until token expiry) - strawman, block it as in G2 |
| Domain-branch audit | Paladin DOMAIN_LOGIC_MODULES = Round 2 domain helper code (e.g. paladin/domains/project/logic) | conventional helper modules | MEDIUM: Paladin already ships per-domain logic directories; the static scan must treat both variants' helper modules identically and the metamorphic test is the primary evidence (behaviour, not file layout) |
| Complexity (comparative) | security_specific_loc includes IR compiler extensions for governance | includes PDP + procedure service | FAIRNESS.md: count compiler/toolchain glue for Paladin like service glue for conventional |

## H26

| Protection | Paladin-shaped mechanism | Strongest conventional equivalent | Fairness risk |
|---|---|---|---|
| Disclosure derived from authority (mechanism claim) | Disclosure rules compiled with the authority contract; generated read surfaces/tools filtered from the same IR | Row/field-level authorization filter in the repository layer driven by the same v3 document (policy-as-data), applied before any response is built | HIGH: conventional must filter at the DATA layer (query rewriting / repository filter), not per-endpoint DTO trimming - DTO-only redaction is the strawman. Ledger row must point to the single filter both read and event paths use |
| Hidden == absent (R26-2) | Engine resolves refs through the observer's view; unknown and hidden share one code path | Repository returns None for filtered rows; one not-found mapper for all endpoints | Medium: the 403/404 split is the typical conventional bug; give the builder PROT-H26 3.1 verbatim (same as Paladin), not a weaker hint |
| Check order (3.2) | Engine authorization before resolution | Middleware authorization before repository fetch | Low; C26-3/C26-7 enforce it for both |
| Tools/schemas (R26-4) | Generated tool surface per principal from IR | Policy-filtered OpenAPI/tool list generated per principal using tool_schema | None: tool_schema is shared and frozen; the only difference is how the allowed set is computed |
| Subscriptions | Engine change feed filtered through the view | Outbox/CDC consumer filtered through the same repository filter | MEDIUM: a conventional CDC that filters only by type (not row/field) leaks; that is a legitimate finding only if the builder was told the frozen event rule (3.5) |
| Provenance redaction (R26-5) | Envelope view projected through the view with explicit markers | Audit-log query service applies the same field-level filter + markers | Low; forms frozen (P1e-5) |
| Determinism | Seeded ids | Seeded ids | Medium: conventional frameworks reach for uuid4; A/A control turns it into INCONCLUSIVE for whichever variant does it - tell both builders the same rule (PROT-H26 s5) |

## Where Paladin advantage could be fabricated (auditor checklist)
1. Conventional built with per-endpoint DTO redaction or token-embedded scopes (strawman) - block.
2. Paladin's read path inherits Round 2 view code while conventional must write a filter from scratch - give both the
   same budget and the same PROT text; count Paladin's generated-surface toolchain LOC.
3. Static domain-branch scan applied to conventional's code layout but not to Paladin's per-domain directories (or vice
   versa) - one scan definition, one DOMAIN_LOGIC_MODULES rule, metamorphic test primary.
4. Pair corpus that only exercises surfaces one variant implements natively (e.g. only object reads) - coverage floors
   per channel (PROT-H26 s9) apply identically.
5. Reason-string differences: H25 freezes the vocabulary (both must match the oracle); H26 compares each variant only
   against itself, so reason style never decides H26.
6. p95 latency descriptive only (contended host, as G2).

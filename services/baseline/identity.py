"""Identity resolution for the baseline variant — reuses
services/identity_resolver.IdentityResolver UNCHANGED (contracts/identity/v1/
mapping_rules.yaml, same rules, same algorithm) per this phase's fairness
choice (see services/baseline/schema.sql's identity_mapping table comment):
the comparison this A/B experiment is designed to make is about the
DECISION/PROVENANCE ARCHITECTURE (RDF+SHACL+PROV graph vs relational
tables), not about identity resolution, which is pure Python with no
storage dependency either way. Persists results as plain rows instead of
oo:IdentityMapping/oo:Quarantined RDF resources — see schema.sql.
"""

from __future__ import annotations

import psycopg

from services.identity_resolver.resolver import IdentityResolver, Quarantined, Resolved, ResolutionResult

_resolver: IdentityResolver | None = None


def get_resolver() -> IdentityResolver:
    global _resolver
    if _resolver is None:
        _resolver = IdentityResolver()
    return _resolver


def resolve_and_store(conn: psycopg.Connection, system: str, local_id: str) -> ResolutionResult:
    """Forward resolution (source-local -> canonical), applied by
    services/baseline/consumer.py at CDC-apply time — same trust boundary
    as the ontology variant's services/ingestion/consumer.py."""
    result = get_resolver().resolve(system, local_id)
    with conn.cursor() as cur:
        if isinstance(result, Resolved):
            cur.execute(
                """
                INSERT INTO identity_mapping (system, source_local_id, canonical_id, rule_id, rule_version, authority, confidence, resolved_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (system, source_local_id) DO UPDATE
                    SET canonical_id = EXCLUDED.canonical_id, rule_id = EXCLUDED.rule_id,
                        rule_version = EXCLUDED.rule_version, authority = EXCLUDED.authority,
                        confidence = EXCLUDED.confidence, resolved_at = EXCLUDED.resolved_at
                """,
                (system, local_id, result.canonical_id, result.rule_id, result.rule_version,
                 result.authority, result.confidence, result.resolved_at),
            )
            cur.execute("DELETE FROM quarantined_identities WHERE system = %s AND source_local_id = %s", (system, local_id))
        else:
            assert isinstance(result, Quarantined)
            cur.execute(
                """
                INSERT INTO quarantined_identities (system, source_local_id, reason, resolved_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (system, source_local_id) DO UPDATE SET reason = EXCLUDED.reason, resolved_at = EXCLUDED.resolved_at
                """,
                (system, local_id, result.reason, result.resolved_at),
            )
    return result


def canonical_id_for(conn: psycopg.Connection, system: str, local_id: str) -> str | None:
    """Point read of an ALREADY-resolved mapping (no re-resolution) —
    used by services/baseline/evidence.py/activities to translate a raw CDC
    row's `part`/`part_id` column into the canonical id evidence/decisions
    key on."""
    with conn.cursor() as cur:
        cur.execute("SELECT canonical_id FROM identity_mapping WHERE system = %s AND source_local_id = %s", (system, local_id))
        row = cur.fetchone()
    return row[0] if row else None


def reverse_lookup(conn: psycopg.Connection, canonical_id: str, system: str) -> str | None:
    """Reverse resolution (canonical -> a SPECIFIC source system's own local
    id) — needed at EXECUTION time the same way
    services/common/identity_lookup.py is: `propose()`'s `parameters.part`
    is canonical-typed, but WMS only understands its own local SKU id."""
    with conn.cursor() as cur:
        cur.execute("SELECT source_local_id FROM identity_mapping WHERE system = %s AND canonical_id = %s LIMIT 1", (system, canonical_id))
        row = cur.fetchone()
    return row[0] if row else None

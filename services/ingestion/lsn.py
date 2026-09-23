"""Postgres LSN <-> comparable integer, and the composite ordering key used
to resolve out-of-order/duplicate CDC (F19/F20/F35: ordering must rely on
source position, never wall clock).
"""

from __future__ import annotations


def lsn_to_int(lsn: str | None) -> int:
    """Postgres LSN is "XXXXXXXX/XXXXXXXX" (two 32-bit hex halves,
    high/low). Debezium's `source.lsn` field is this same format as a
    plain integer already in newer connector versions, but some paths
    (and Debezium's own docs) still show the slash form — accept both.
    None (e.g. a field genuinely absent) sorts as 0, the lowest possible
    position, never as "newer"."""
    if not lsn:
        return 0
    lsn = str(lsn)
    if "/" in lsn:
        high, low = lsn.split("/", 1)
        return (int(high, 16) << 32) | int(low, 16)
    return int(lsn)


def ordering_key(source_lsn: str | int | None, source_version: int | None) -> tuple[int, int]:
    """(lsn, row-version) compared lexicographically. lsn is the primary
    ordering signal (F35: never wall clock); the row's own optimistic-
    concurrency `version` column is the tiebreaker for the rare case of
    two events sharing one LSN (e.g. a snapshot read before real LSNs
    exist, source_lsn None -> 0 for all of them)."""
    lsn_int = lsn_to_int(str(source_lsn) if source_lsn is not None else None)
    return (lsn_int, int(source_version) if source_version is not None else 0)

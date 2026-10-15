"""G5-E33 (d): world_log integrity observations made by the harness. At every RC1 and at the end of the sequence the harness reads the whole
shared world_log (the one variant-process file the oracle reads), checks seq is strictly increasing without gaps from 1, and hashes the
prefix it already read at the previous observation: a changed prefix (or a shorter log) is recorded here and judged as world_log_rewritten.
Only raw observations are recorded; the judge converts them (judge_wl)."""
from __future__ import annotations

import hashlib

from r3_shared.extadapter import canon_json
from r3_shared.world import WorldReader


def digest(rows: list) -> str:
    h = hashlib.sha256()
    for x in rows:
        h.update(canon_json(x).encode())
        h.update(b"\n")
    return h.hexdigest()


def seq_gap(rows: list):
    """None when seq is 1,2,3,... without gaps or repeats; else the first offending (index, seq)."""
    for i, x in enumerate(rows):
        if x["seq"] != i + 1:
            return {"index": i, "seq": x["seq"], "expected": i + 1}
    return None


def observe_rows(r, where: str, rows: list) -> dict:
    """Record one observation on the run `r` (r.wl list; r._wl_prev = (n, hash of rows[:n]) of the previous observation)."""
    prev = getattr(r, "_wl_prev", None)
    if not hasattr(r, "wl"):
        r.wl = []
    obs = {"where": where, "t": r.t, "n": len(rows), "gap": seq_gap(rows), "prefix_changed": None}
    if prev is not None:
        pn, ph = prev
        obs["prefix_changed"] = len(rows) < pn or digest(rows[:pn]) != ph
        obs["prev_n"] = pn
    r._wl_prev = (len(rows), digest(rows))
    r.wl.append(obs)
    return obs


def observe_path(r, where: str) -> None:
    if not hasattr(r, "wl"):
        r.wl = []
    try:
        rd = WorldReader(r.world_path)
        try:
            rows = rd.log()
        finally:
            rd.close()
    except Exception as exc:  # noqa: BLE001 - B4 deletes the store on purpose; an unreadable store is recorded, never a pass
        r.wl.append({"where": where, "t": r.t, "error": f"{type(exc).__name__}: {exc}"[:160]})
        return
    observe_rows(r, where, rows)

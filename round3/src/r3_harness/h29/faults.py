"""FROZEN fault catalogue (ORACLE-AND-HARNESS-G5 s4) and envelope validity (spec/gate5/envelope-ops.json). Maps each envelope class to
its injector and expected oracle consequence; validates a generated sequence against the envelope bounds. Hash frozen in FREEZE_G5."""
from __future__ import annotations

import json
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[3]
OPS = json.loads((ROUND3 / "spec" / "gate5" / "envelope-ops.json").read_text())
C = OPS["constants"]
LEASE, PARTITION_MAX, LAG_MAX, WINDOW = C["LEASE"], C["PARTITION_MAX"], C["LAG_MAX"], C["WINDOW"]
REDELIVERY_MAX, CRASHES_MAX = C["REDELIVERY_MAX"], C["CRASHES_PER_SEQUENCE_MAX"]
CRASH_POINTS = tuple(OPS["crash_points"])
FORBIDDEN_SETS = tuple(frozenset(s) for s in OPS["composition"]["forbidden_node_sets"])

CATALOGUE = {   # id -> (class, injector, expected oracle consequence)
    "F1-CPn": ("F1", "arm CPn at key, SIGKILL, resume (RC1, RC2)", "in-flight request UNRESOLVED; committed set exact at RC1; no duplicate after redelivery"),
    "F2-out": ("F2", "AuthorityService outage(drop) [a,b)", "lease-window requests SAFE (R29-0); after it BLOCKED (UNAVAILABLE AUTH)"),
    "F2-rl": ("F2", "AuthorityService partition(reply_lost)", "same classification as F2-out"),
    "F3-down": ("F3", "ExternalWorld outage(S)", "decisions SAFE; intents on S PENDING/UNKNOWN; other systems SAFE"),
    "F3-byz": ("F3", "frozen H28 catalogue primitive on S", "H28 classes"),
    "F4-dup": ("F4", "redeliver request_id (sequential / concurrent 2-3 copies)", "one commit, original decision repeated"),
    "F4-ord": ("F4", "approve after request; reconcile watermarks out of order; observer lag", "oracle decisions per actual order; outcome monotone"),
    "F5-part": ("F5", "partition {node} or {node1,node2}, drop / reply_lost", "per-node BLOCKED/UNRESOLVED; unrelated ops SAFE"),
    "F6-stale": ("F6", "publish(narrowed doc) during lease / outage / crash window", "stale-sensitive request DENIED or UNAVAILABLE AUTH, never OK"),
    "F7-comp": ("F7", "attacker agent schedule", "P1/P2 classes 0"),
    "F8-tamper": ("F8", "TamperView op while host dead", "R27-5: non-OK with zero effect or exactly untampered behaviour"),
}
FAULT_CLASS_NODES = {"F2": ("AUTH",), "F5": ("AUTH", "ANCHOR", "EXT", "OBS"), "F3": ("EXT",)}


def window_nodes(steps: list) -> list:
    """[(fid, cls, node, mode, start_index, duration)] of every fault_start step."""
    return [(s["fid"], s["cls"], s["node"], s["mode"], i, s["duration"]) for i, s in enumerate(steps) if s["op"] == "fault_start"]


def envelope_ok(seq: dict) -> tuple[bool, str]:
    """The generator enforces these bounds; a draw outside is re-drawn (counted). Also used by tests on hand-made sequences."""
    steps, crashes = seq["steps"], [s for s in seq["steps"] if s["op"] == "crash"]
    if len(crashes) > CRASHES_MAX:
        return False, "too many crashes"
    # replay the clock over advance steps to find concurrent fault classes and node sets
    t, act = 0, []
    for s in steps:
        if s["op"] == "advance":
            t += s["n"]
        elif s["op"] == "fault_start":
            if s["duration"] > PARTITION_MAX or s["duration"] < 1:
                return False, "fault duration outside PARTITION_MAX"
            act.append((t, t + s["duration"], s["cls"], s["node"].split(":")[0]))
        elif s["op"] == "redeliver" and s["copies"] > REDELIVERY_MAX:
            return False, "redelivery beyond REDELIVERY_MAX"
    pts = sorted({a[0] for a in act})
    for p in pts:
        live = [a for a in act if a[0] <= p < a[1]]
        if len({a[2] for a in live}) > 2:
            return False, ">2 concurrent classes"
        if len({a[3] for a in live if a[3] in ("AUTH", "ANCHOR", "OBS")}) >= 3:
            return False, "forbidden node set down together"
        ext = {s["node"] for s in steps if s["op"] == "fault_start" and s["node"].startswith("EXT:")}
        if len(ext) > 1:
            return False, "more than one external system faulted"
    if sum(1 for s in steps if s["op"] == "tamper") > 1:
        return False, "more than one tamper"
    return True, ""

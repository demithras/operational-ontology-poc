"""H29 dependency oracle (PROT-H29 1.3-1.5, 3; ORACLE-AND-HARNESS-G5 s1). PURE: imports r3_shared forms/rules and r3_oracle only - never a
variant, never r3_harness, never HistoryStore. Ticks are RELATIVE to the sequence base (the loader subtracts it).
Inputs only: the frozen dependency graph, the SERVICE fault/publish logs, the harness send/kill/resume log. Never a reply, never a
variant self-report. Total: absent -> explicit value, no exceptions.

Classes (PROT-H29 1.4): SAFE_TO_RUN | BLOCKED_BY_DEPENDENCY | UNRESOLVED."""
from __future__ import annotations

from dataclasses import dataclass, field

SAFE, BLOCKED, UNRESOLVED = "SAFE_TO_RUN", "BLOCKED_BY_DEPENDENCY", "UNRESOLVED"
LEASE_DEFAULT = 4
MUTATION_KINDS = ("request", "approve", "delegate", "revoke")        # surface governed_mutation
AUTH_KINDS = MUTATION_KINDS + ("read",)                              # decision deps contain AUTH (graph-checked below)
INPUT_INVALID = ("schema_invalid", "unknown_operation", "unknown_tool", "bad_args")


# ---- dependency graph (data) ----------------------------------------------------------------------------------------
def surface_of(graph: dict, domain: str, kind: str, op: str | None) -> str:
    if kind == "read":
        return "read"
    if kind in ("replay", "explain", "reconcile"):
        return kind
    return "governed_mutation"


def decision_deps(graph: dict, domain: str, kind: str, op: str | None) -> list[str]:
    s = graph["surfaces"].get(surface_of(graph, domain, kind, op), {})
    return list(s.get("decision", []))


def outcome_deps(graph: dict, domain: str, op: str | None) -> list[str]:
    ops = graph["operations"]
    ent = (ops.get(domain, {}) or {}).get(op) or (ops.get("*", {}) or {}).get(op) or {}
    return list(ent.get("outcome", []))


# ---- fault state Phi(t) from SERVICE logs + the harness kill/resume log ----------------------------------------------
@dataclass
class Phi:
    """windows: [{node, mode, from_tick, to_tick}] (node = AUTH | ANCHOR | EXT:<S> | OBS); engine: [(kill_tick, resume_tick|None)]."""
    windows: list = field(default_factory=list)
    engine: list = field(default_factory=list)

    def mode(self, node: str, t: int):
        """'drop' | 'reply_lost' | None (drop wins when both cover t)."""
        ms = {w["mode"] for w in self.windows if w["node"] == node and w["from_tick"] <= t < w["to_tick"]}
        return "drop" if "drop" in ms else ("reply_lost" if ms else None)

    def down(self, t: int, nodes=None) -> dict:
        ns = nodes if nodes is not None else sorted({w["node"] for w in self.windows})
        return {n: m for n in ns if (m := self.mode(n, t))}

    def engine_down(self, t: int) -> bool:
        return any(k <= t and (r is None or t < r) for k, r in self.engine)

    def restart_between(self, s: int, t: int) -> bool:
        """An ENGINE restart (kill or resume) inside [s, t]."""
        return any(s <= k <= t or (r is not None and s <= r <= t) for k, r in self.engine)

    def active_classes(self, t: int) -> list:
        return sorted({w.get("cls") for w in self.windows if w["from_tick"] <= t < w["to_tick"] and w.get("cls")})


def phi_from_logs(auth_faults, anchor_windows, ext_windows, obs_windows, kills) -> Phi:
    """auth_faults: AuthorityService faults rows; anchor_windows: AnchorServer windows; ext_windows: ExternalWorld armed windows
    (each with `target` = system); obs_windows: harness ObserverFault log; kills: [(kill_tick, resume_tick)]. All service-recorded
    except OBS (client-side fault, PROTOCOL-P1g P1g-3) and the kill/resume pairs (harness log)."""
    w = []
    for f in auth_faults:
        w.append({"node": "AUTH", "mode": f["mode"], "from_tick": f["from_tick"], "to_tick": f["to_tick"], "dep": f.get("deployment")})
    for f in anchor_windows:
        w.append({"node": "ANCHOR", "mode": f["mode"], "from_tick": f["from_tick"], "to_tick": f["to_tick"], "dep": f.get("deployment")})
    for f in ext_windows:
        w.append({"node": f"EXT:{f['target']}", "mode": f["mode"], "from_tick": f["from_tick"], "to_tick": f["to_tick"],
                  "dep": f.get("deployment")})
    for f in obs_windows:
        w.append({"node": "OBS", "mode": "drop", "from_tick": f["from_tick"], "to_tick": f["to_tick"], "dep": None})
    return Phi(w, [tuple(k) for k in kills])


# ---- authority in force and the lease rule (P1g-2, G5-E3) ----------------------------------------------------------
def authority_in_force(versions: list, t: int):
    """A(t): digest with the greatest effective_tick <= t (ties: greatest seq); None before any version. versions = log rows."""
    best = None
    for v in versions:
        if v["effective_tick"] <= t and (best is None or (v["effective_tick"], v["seq"]) > (best["effective_tick"], best["seq"])):
            best = v
    return None if best is None else best["digest"]


def doc_of(versions: list, digest: str):
    return next((v["doc"] for v in versions if v["digest"] == digest), None)


def grant_until(versions: list, s: int, lease: int = LEASE_DEFAULT) -> int:
    """lease_until the P1g-2 rule grants to a fetch at tick s: s + LEASE, shortened to the earliest pending effective tick."""
    pend = [v["effective_tick"] for v in versions if v["effective_tick"] > s and v["requested_tick"] <= s]
    return s + lease if not pend else min(s + lease, min(pend))


def lease_valid(g: int, until: int, t: int) -> bool:
    return g <= t < until          # strict upper bound


def lease_sends(sends: list, phi: Phi, graph: dict, domain: str) -> list:
    """Ticks s of sends that renew the lease (R29-0): AUTH-dependent, schema-valid probe-free requests with AUTH up at s."""
    out = []
    for q in sends:
        if q.get("invalid_probe") or "AUTH" not in decision_deps(graph, domain, q["kind"], q.get("op")):
            continue
        if phi.mode("AUTH", q["t"]) is None and not phi.engine_down(q["t"]):
            out.append(q["t"])
    return sorted(set(out))


def lease_cover(t: int, sends_ticks: list, versions: list, phi: Phi, lease: int = LEASE_DEFAULT):
    """(covered, strict): some renewing send s <= t whose granted lease is valid at t. strict = no ENGINE restart in [s, t]."""
    best = None
    for s in sends_ticks:
        if s <= t and lease_valid(s, grant_until(versions, s, lease), t):
            strict = not phi.restart_between(s, t)
            if best is None or (strict and not best[1]):
                best = (True, strict)
    return best or (False, False)


# ---- classification (PROT-H29 1.4) ----------------------------------------------------------------------------------
@dataclass
class Cls:
    kind: str
    down: list              # down nodes among deps(op, decision) at t (empty for SAFE)
    strict: bool = True     # SAFE only: must progress (False = lease use after an ENGINE restart: permitted, not required)
    reason: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "down": list(self.down), "strict": self.strict, "reason": self.reason}


def classify(q: dict, phi: Phi, graph: dict, domain: str, renew_ticks: list, versions: list, crashed_rids=frozenset(),
             lease: int = LEASE_DEFAULT) -> Cls:
    """q = {kind, op, t, rid}. Decision plane only; never reads a reply."""
    t = q["t"]
    deps = decision_deps(graph, domain, q["kind"], q.get("op"))
    if q.get("rid") in crashed_rids:
        return Cls(UNRESOLVED, [], True, "in flight at / redelivery after an ENGINE crash")
    down = phi.down(t, deps)
    if "ANCHOR" in down and down["ANCHOR"] == "reply_lost":
        return Cls(UNRESOLVED, sorted(down), True, "ANCHOR reply_lost: commit status in doubt")
    if not down:
        return Cls(SAFE, [], True, "all decision dependencies up")
    if set(down) == {"AUTH"}:
        covered, strict = lease_cover(t, renew_ticks, versions, phi, lease)
        if covered:
            return Cls(SAFE, [], strict, "AUTH down inside a lease window")
    left = sorted(n for n in down if n != "AUTH" or not lease_cover(t, renew_ticks, versions, phi, lease)[0])
    return Cls(BLOCKED, left or sorted(down), True, "decision dependency down")


def blocked_reply_ok(cls: Cls, status: str, body: dict, input_invalid: bool, reason_map: dict | None = None) -> tuple[bool, str]:
    """R29-6/R29-7 for a BLOCKED / UNRESOLVED-with-dependency request. -> (admissible, why-not). OK is never admissible."""
    reason = (body or {}).get("reason")
    if status == "UNAVAILABLE":
        if reason == "dependency_unavailable" and (body or {}).get("dependency") in cls.down:
            return True, ""
        if reason == "crashed" and cls.kind == UNRESOLVED:
            return True, ""
        return False, f"UNAVAILABLE {reason!r} names {(body or {}).get('dependency')!r}, down={cls.down}"
    if status == "UNKNOWN":
        return (reason in ("crashed", "in_doubt")), ("" if reason in ("crashed", "in_doubt") else f"UNKNOWN reason {reason!r}")
    if status == "INVALID":
        mapped = (reason_map or {}).get(reason, reason)
        ok = input_invalid and mapped in INPUT_INVALID
        return ok, ("" if ok else f"INVALID {reason!r} on a request the oracle finds input-valid or outside the input-invalid set")
    return False, f"{status} while a dependency is down"

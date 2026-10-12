"""Fault episodes of the H29 generator (one function per envelope class, ORACLE-AND-HARNESS-G5 s4). Each episode appends steps to a
Plan, keeps its own faults inside the envelope bounds and ends with every window healed or scheduled to end. Never raises."""
from __future__ import annotations

from . import faults, gen_draw, gen_emit as E
from .faults import LEASE, PARTITION_MAX


def _ext_systems(plan) -> list:
    return sorted(s for s in plan.systems["systems"] if s != "GEN-NULL")


def f1_crash(plan, ch, cp: str, var: int = 0) -> None:
    t0 = plan.t
    if cp in ("CP1_before_commit", "CP2_after_commit", "CP3_after_anchor_append", "CP6_idle"):
        pick = gen_draw.draw(plan, ch, "ok_local") or gen_draw.draw(plan, ch, "ok")
        if pick is None:
            return
        rid = plan.new_rid("c")
        E.crash(plan, cp, rid)
        plan.advance(1)
        kill_t = plan.t
        _, cls = E.request(plan, pick, rid=rid, predict=cp != "CP1_before_commit")
        if cp != "CP6_idle":
            plan.crashed.add(rid)
        plan.advance(1)
        E.resume(plan, kill_t)
        E.fill(plan, ch, 2)
        plan.add({"op": "redeliver", "rid": rid, "copies": 1, "concurrent": False})
        plan.note_send("request", pick["operation"], rid)
        E.recovery(plan)
        E.fill(plan, ch, 2, tag="post")
    elif cp in ("CP4_adapter_before_apply", "CP5_adapter_after_apply"):
        s = ch.choice(_ext_systems(plan))
        pick = gen_draw.draw(plan, ch, "ok_ext", system=s)
        if pick is None:
            return
        rid = plan.new_rid("c")
        E.crash(plan, cp, E.corr(rid, 0))
        plan.advance(1)
        kill_t = plan.t
        E.request(plan, pick, rid=rid)
        E.dispatch(plan)
        plan.advance(1)
        E.resume(plan, kill_t)
        E.dispatch(plan)
        plan.advance(1)
        plan.add({"op": "redeliver", "rid": rid, "copies": 1, "concurrent": False})
        plan.note_send("request", pick["operation"], rid)
        E.recovery(plan)
        E.fill(plan, ch, 2, tag="post")
    elif cp == "CP7_reconcile_after_read":
        s = ch.choice(_ext_systems(plan))
        pick = gen_draw.draw(plan, ch, "ok_ext", system=s)
        if pick is None:
            return
        rid, _ = E.request(plan, pick)
        E.dispatch(plan)
        plan.advance(2)
        E.crash(plan, cp, rid)
        kill_t = plan.t
        E.reconcile(plan, rid)
        plan.advance(1)
        E.resume(plan, kill_t)
        E.dispatch(plan)
        E.recovery(plan)
        E.fill(plan, ch, 2, tag="post")
    else:   # CP8: crash during recovery - first crash (CP2), resume, then the first dispatch after resume dies
        pick = gen_draw.draw(plan, ch, "ok_ext") or gen_draw.draw(plan, ch, "ok")
        if pick is None:
            return
        rid = plan.new_rid("c")
        E.crash(plan, "CP2_after_commit", rid)
        plan.advance(1)
        kill_t = plan.t
        E.request(plan, pick, rid=rid)
        plan.crashed.add(rid)
        plan.advance(1)
        E.resume(plan, kill_t)
        E.crash(plan, cp, "dispatch_pending")
        kill2 = plan.t
        E.dispatch(plan)
        plan.advance(1)
        E.resume(plan, kill2)
        E.dispatch(plan)
        E.recovery(plan)
        E.fill(plan, ch, 2, tag="post")


def f2_auth(plan, ch, mode: str, var: int, cls: str = "F2", tail: bool = True) -> None:
    """AuthorityService outage (drop) / partition (reply_lost). var%3==0: starts right after a renewal (lease window exists);
    otherwise the last renewal is older than LEASE (no lease)."""
    E.fill(plan, ch, 1, tag="renew")
    in_lease = var % 3 != 2
    if not in_lease:
        plan.advance(LEASE + 1)
        E.fill(plan, ch, 1, tag="renew")
        plan.advance(LEASE)               # renewal is older than LEASE
    dur = min(PARTITION_MAX, ch.randint(LEASE + 2, PARTITION_MAX))
    plan.advance(1)
    plan.fault(cls, "AUTH", mode, dur)
    s0 = plan.t - 1
    inside = [1, 2] if in_lease else [0]
    for off in (0, 1, 2, 3, 4, 5) if in_lease else (0, 2):
        if s0 + off >= plan.t:
            plan.advance(s0 + off - plan.t)
        e = gen_draw.draw(plan, ch, "ok")
        if e is not None:
            E.request(plan, e, tag="lease" if off + s0 + 1 <= s0 + LEASE - 1 else "past_lease")
    if plan.t < plan.windows[-1]["to_tick"]:
        plan.heal(plan.windows[-1]["fid"])                 # fault_heal: the driver advances to the end of the window
    if tail:
        E.fill(plan, ch, 1)


def f3_ext(plan, ch, byz: bool, var: int) -> None:
    syss = _ext_systems(plan)
    s = syss[var % len(syss)]
    others = [x for x in syss if x != s]
    pick = gen_draw.draw(plan, ch, "ok_ext", system=s)
    if pick is None:
        return
    rid1, _ = E.request(plan, pick)
    E.dispatch(plan)
    if not byz:
        plan.advance(1)
        dur = ch.randint(3, PARTITION_MAX)
        plan.fault("F3", f"EXT:{s}", "drop", dur)
        for sysx in ([s] + others[:1]) * 1:
            p2 = gen_draw.draw(plan, ch, "ok_ext", system=sysx)
            if p2 is not None:
                E.request(plan, p2)
                E.dispatch(plan)
                plan.advance(1)
        E.fill(plan, ch, 3)
        E.dispatch(plan)
        E.close_windows(plan)
        plan.advance(1)
        E.dispatch(plan)
    else:
        E.fill(plan, ch, 1)
        E.dispatch(plan)
    plan.advance(2)


def f4_events(plan, ch, var: int) -> None:
    rid = (E.fill(plan, ch, 1) or [None])[0]
    kind = var % 3
    if rid and kind == 0:
        plan.add({"op": "redeliver", "rid": rid, "copies": ch.randint(1, 3), "concurrent": False})
        plan.note_send("request", None, rid)
    elif rid and kind == 1:
        plan.add({"op": "redeliver", "rid": rid, "copies": ch.randint(2, 3), "concurrent": True})
        plan.note_send("request", None, rid)
    else:                                   # reorder: request first (approval required -> DENIED), approve it, then the same request again
        if E.healthy(plan):
            pick = gen_draw.draw(plan, ch, "approved")
            if pick is not None:
                E.request(plan, {**pick, "dec": None}, tag="needs_approval", predict=False)
                plan.advance(1)
                plan.add({"op": "approve", "approver": pick["approver"], "requester": pick["principal"], "obo": None,
                          "operation": pick["operation"], "args": pick["args"]})
                plan.note_send("approve", pick["operation"], None)
                plan.rep.approve(plan.doc(), pick["approver"], pick["principal"], None, pick["operation"], pick["args"])
                dec, akey = plan.rep.decide(plan.doc(), pick["principal"], None, pick["operation"], pick["args"], plan.t, None)
                plan.advance(1)
                E.request(plan, {**pick, "dec": dec, "akey": akey}, tag="approved")
    s = ch.choice(_ext_systems(plan))
    p = gen_draw.draw(plan, ch, "ok_ext", system=s)
    if p is not None:
        r, _ = E.request(plan, p)
        E.dispatch(plan)
        plan.advance(2)
        E.reconcile(plan, r)
        E.reconcile(plan, r, watermark=max(0, plan.t - 1))      # out-of-order watermark (G4-E16): outcome stays monotone
    plan.mark_class("F4", 0, plan.t + 1)


def f5_partition(plan, ch, var: int, nodes=None) -> None:
    E.fill(plan, ch, 1, tag="renew")
    syss = _ext_systems(plan)
    sx = syss[var % len(syss)]
    pool = ["ANCHOR", "OBS", "EXT:" + sx]
    combos = [["ANCHOR"], ["OBS"], ["EXT:" + sx], ["ANCHOR", "OBS"], ["OBS", "EXT:" + sx]]
    nodes = nodes or combos[var % len(combos)]
    dur = ch.randint(5, PARTITION_MAX)
    modes = ["drop", "reply_lost"]
    plan.advance(1)
    for n in nodes:
        plan.fault("F5", n, ch.choice(modes) if n != "OBS" else "drop", dur)
    for it in range(2):
        for _k in range(2):
            e = gen_draw.draw(plan, ch, "ok")
            if e is not None:
                E.request(plan, e, tag="partition")
        if "ANCHOR" in nodes:
            E.read(plan, gen_draw.any_read(plan, ch), tag="unrelated")
        p = gen_draw.draw(plan, ch, "ok_ext", system=sx)
        if p is not None and it == 0 and not any(n == "ANCHOR" for n in nodes):
            r, _ = E.request(plan, p)
            E.dispatch(plan)
            E.reconcile(plan, r)
        plan.advance(1)
    E.close_windows(plan)
    E.fill(plan, ch, 1)


def f6_stale(plan, ch, var: int) -> None:
    """Publish a narrowed version while the variant holds a lease (var%3==0), while AUTH is faulted (1), or while ENGINE is down (2);
    then stale-sensitive requests/reads sent after the effective tick (computed by the same lease rule)."""
    ks = list(range(1, len(plan.fam)))
    E.fill(plan, ch, 1, tag="renew")
    off, k, pair0 = ch.randint(0, 999), None, None
    for j in range(len(ks)):
        kk = ks[(var * 7 + off + j) % len(ks)]
        pair0 = gen_draw.stale_pair(plan, ch, kk)
        if pair0 is not None:
            k = kk
            break
    if k is None:
        return False
    mode = var % 3
    if mode == 1:
        plan.advance(1)
        plan.fault("F6", "AUTH", "drop", PARTITION_MAX)
    if mode == 2:
        pk = gen_draw.draw(plan, ch, "ok_local") or gen_draw.draw(plan, ch, "ok")
        if pk is None:
            return False
        rid = plan.new_rid("c")
        E.crash(plan, "CP6_idle", rid)
        plan.advance(1)
        kill_t = plan.t
        E.request(plan, pk, rid=rid)
        plan.advance(1)
        row = E.publish(plan, k)
        plan.advance(max(1, row["effective_tick"] - plan.t + 1))
        plan.fault("F6", "AUTH", "drop", PARTITION_MAX)
        E.resume(plan, kill_t)
    else:
        row = E.publish(plan, k)
    f = row["effective_tick"]
    pair = gen_draw.stale_pair(plan, ch, k) or pair0
    rd = gen_draw.read_pair(plan, ch, k)
    plan.mark_class("F6", plan.t, f + 3)
    for target in (f, f + 1, f + 2):
        if target > plan.t:
            plan.advance(target - plan.t)
        elif mode == 0 and target == plan.t:
            pass
        cand = gen_draw.stale_ok(plan, pair, k) or gen_draw.stale_pair(plan, ch, k)
        if cand is None:
            continue
        pair = cand
        E.request(plan, {**pair, "dec": None}, tag="stale", predict=False)      # DENIED under the version in force: nothing commits
        if rd is not None:
            E.read(plan, rd, tag="stale")
        E.fill(plan, ch, 1, gap=0)                                                # an unrelated OK request inside the stale window
    plan.stats["stale_sensitive"] = plan.stats.get("stale_sensitive", 0) + 1
    E.close_windows(plan)
    E.fill(plan, ch, 1)
    return True


def f7_attacker(plan, ch, var: int) -> None:
    hostile = [p["id"] for p in plan.auth0["principals"] if p.get("hostile")] or gen_draw.principals(plan, kinds=("agent",))
    who = hostile[0] if hostile else gen_draw.principals(plan)[0]
    plan.stats["attacker"] = who
    rid0 = (E.fill(plan, ch, 1) or [None])[0]
    if var % 2:
        plan.advance(1)
        plan.fault("F7", "AUTH", "drop", ch.randint(4, 8))
    for _ in range(3):
        d = gen_draw.draw(plan, ch, "deny", who=who)
        if d is not None:
            E.request(plan, d, attacker=True, tag="attack")
        plan.advance(1)
    if rid0:                                   # replay another principal's request_id with different content
        d = gen_draw.draw(plan, ch, "deny", who=who)
        if d is not None:
            E.request(plan, d, attacker=True, rid=rid0, predict=False, tag="rid_replay")
    plan.add({"op": "delegate", "principal": who, "edge": {"id": "e-probe"}, "rid": plan.new_rid("d")})     # malformed edge: must not commit
    plan.note_send("request", None, None)
    plan.add({"op": "revoke", "principal": who, "edge_id": "e-unknown", "rid": plan.new_rid("v")})
    plan.note_send("request", None, None)
    plan.mark_class("F7", 0, plan.t + 1)
    E.close_windows(plan)
    E.fill(plan, ch, 1)


def f8_tamper(plan, ch, var: int) -> None:
    rid = E.approve_flow(plan, ch) or (E.fill(plan, ch, 1) or [None])[0]
    rids = E.fill(plan, ch, 2)
    pk = gen_draw.draw(plan, ch, "ok_local") or gen_draw.draw(plan, ch, "ok")
    if pk is None:
        return
    key = plan.new_rid("c")
    E.crash(plan, "CP6_idle", key)
    plan.advance(1)
    kill_t = plan.t
    E.request(plan, pk, rid=key)
    plan.advance(1)
    plan.add({"op": "tamper", "what": faults_tamper(var)})
    E.resume(plan, kill_t)
    for r in ([rid] if rid else []) + rids[:1] + [key]:
        plan.add({"op": "redeliver", "rid": r, "copies": 1, "concurrent": False})
        plan.note_send("request", None, r)
    E.fill(plan, ch, 3)
    E.recovery(plan)
    E.fill(plan, ch, 2, tag="post")
    plan.mark_class("F8", kill_t, plan.t + 1)


def faults_tamper(var: int) -> str:
    from .rules import TAMPER_KINDS
    return TAMPER_KINDS[var % len(TAMPER_KINDS)]

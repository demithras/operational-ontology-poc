"""Step emitters for the H29 generator: each appends frozen-vocabulary steps to a Plan and updates the predicted world / classes."""
from __future__ import annotations

from r3_oracle import continuity as C
from r3_oracle import extoracle
from r3_shared.extadapter import correlation

from . import faults, gen_draw


def healthy(plan) -> bool:
    """No decision-plane fault and no open recovery at the current tick (approve/delegate/revoke are generated only here)."""
    return not plan.phi.down(plan.t, ("AUTH", "ANCHOR")) and not plan.phi.engine_down(plan.t)


def request(plan, pick, tag=None, surface="direct", rid=None, attacker=False, predict=True, step_extra=None):
    """Append a request step for `pick` (gen_draw result). -> (rid, Cls). Predicts the commit when the oracle class is SAFE."""
    rid = rid or plan.new_rid()
    st = {"op": "request", "i": len(plan.sends), "principal": pick["principal"], "obo": None, "operation": pick["operation"],
          "args": pick["args"], "rid": rid, "surface": surface}
    if tag:
        st["tag"] = tag
    if attacker:
        st["attacker"] = True
    if pick.get("invalid"):
        st["invalid_probe"] = True
    if step_extra:
        st.update(step_extra)
    plan.add(st)
    cls = plan.note_send("request", pick["operation"], rid, invalid=bool(pick.get("invalid")))
    dec = pick.get("dec")
    if predict and cls.kind == C.SAFE and dec is not None and dec.kind == "OK" and dec.outcome.effects and not plan.phi.engine_down(plan.t):
        plan.rep.commit(dec, pick["akey"], rid)
        ints = extoracle.intended(plan.systems, dec, rid)
        if ints:
            plan.intents[rid] = (plan.t, ints)
    return rid, cls


def approve_flow(plan, ch, surface="direct", system=None):
    """approve -> request (consumes the approval) in a healthy window; -> rid or None."""
    if not healthy(plan):
        return None
    pick = gen_draw.draw(plan, ch, "approved", system=system)
    if pick is None:
        return None
    plan.add({"op": "approve", "approver": pick["approver"], "requester": pick["principal"], "obo": None,
              "operation": pick["operation"], "args": pick["args"]})
    plan.note_send("approve", pick["operation"], None)
    plan.rep.approve(plan.doc(), pick["approver"], pick["principal"], None, pick["operation"], pick["args"])
    dec, akey = plan.rep.decide(plan.doc(), pick["principal"], None, pick["operation"], pick["args"], plan.t, None)
    pick = {**pick, "dec": dec, "akey": akey}
    return request(plan, pick, tag="approved", surface=surface)[0]


def read(plan, rd, tag=None):
    st = {"op": "read", "i": len(plan.sends), "principal": rd["principal"], "operation": rd["operation"], "args": rd["args"]}
    if tag:
        st["tag"] = tag
    plan.add(st)
    plan.note_send("read", None, None)


def fill(plan, ch, n: int, want="ok", gap=1, system=None, tag=None):
    """n oracle-OK requests, `gap` ticks apart (advance BEFORE each so a fault_start never shares a tick with an earlier send)."""
    rids = []
    for _ in range(n):
        plan.advance(gap)
        p = gen_draw.draw(plan, ch, want, system=system)
        if p is not None:
            rids.append(request(plan, p, tag=tag, surface=ch.choice(["direct", "call_tool"]))[0])
    return rids


def dispatch(plan):
    plan.add({"op": "dispatch"})


def reconcile(plan, rid, lag=None, watermark=None):
    st = {"op": "reconcile", "rid": rid, "watermark": plan.t if watermark is None else watermark}
    if lag:
        st["lag"] = lag
    plan.add(st)


def crash(plan, point: str, key: str):
    plan.add({"op": "crash", "point": point, "key": key})


def resume(plan, killed_at: int):
    """resume at the current tick (> kill tick); the driver runs RC1 and then advances ONE tick (ORACLE-AND-HARNESS-G5 s2)."""
    plan.add({"op": "resume"})
    plan.kills.append((killed_at, plan.t))
    plan.phi = C.Phi(plan.windows, plan.kills)
    plan.t += 1
    plan.mark_class("F1", killed_at, plan.t + 1)


def corr(rid: str, idx: int = 0) -> str:
    return correlation(rid, idx)


def close_windows(plan) -> None:
    """Advance past every scheduled window (heal all faults)."""
    end = max([w["to_tick"] for w in plan.windows] or [0])
    if plan.t < end:
        plan.advance(end - plan.t)


def publish(plan, k: int):
    plan.add({"op": "publish_authority", "version": k})
    return plan.model.publish(plan.fam[k], plan.t)

"""Decision / review / appeal plays of the H25 case generator. All targeting reads the oracle MIRROR (g.M)."""
from __future__ import annotations

from r3_oracle import const_eval as E

INF = 10 ** 9
VALUES = {"decision": ("concur", "dissent"), "review": ("uphold", "overturn")}


def stage_of(g, cid, stage):
    c = g.M.case(cid)
    d = E.decision(g.M.doc, g.ops, c, INF, g.tick())
    return d if stage == "decision" else E.review(g.M.doc, g.ops, c, d, INF)


def bodies_of(g, cid, stage) -> list[str]:
    c = g.M.case(cid)
    d = E.decision(g.M.doc, g.ops, c, INF, g.tick())
    if stage == "decision":
        return d["bodies"]
    rv = d["matter"]["review"] if d["matter"] else None
    return [rv["by"]] if rv and E.appealed(c, INF) else []


def members(g, cid, stage) -> list[str]:
    c = g.M.case(cid)
    out: list[str] = []
    for b in bodies_of(g, cid, stage):
        out += [m for m in E.eligible(g.M.doc, b, c["requester"]) if m not in out]
    return out


def cast(g, cid, stage, who, value=None):
    value = value or g.jrng.choice(VALUES[stage] + ("abstain",) if g.jrng.random() < 0.15 else VALUES[stage])
    return g.step(who, {"kind": "judge", "case": cid, "stage": stage, "value": value, "merit": g.merit()})


def stray(g, cid, stage):
    """A judge action that should be refused: outsider, recused requester, duplicate, wrong stage, closed stage."""
    c = g.M.case(cid)
    el = members(g, cid, stage)
    pool = [p for p in g.principals() if p not in el]
    r = g.rng.random()
    if r < 0.4 and pool:
        return cast(g, cid, stage, g.rng.choice(pool))
    if r < 0.6 and el:
        return cast(g, cid, stage, g.rng.choice(el), "dissent" if stage == "decision" else "overturn")  # maybe duplicate
    if r < 0.8:
        other = "review" if stage == "decision" else "decision"
        return cast(g, cid, other, g.rng.choice(g.principals()))
    return cast(g, cid, stage, c["requester"])


def run_stage(g, cid, stage, mode):
    """Cast judgments for a stage. mode: complete (allow-ish) | dissent | partial | none."""
    el = list(members(g, cid, stage))
    g.rng.shuffle(el)
    c = g.M.case(cid)
    ks = [E.body_of(g.M.doc, b)["rule"].get("k", 1) for b in bodies_of(g, cid, stage)]
    need = max(ks) if ks else 1
    yes, no = VALUES[stage]
    limit = {"complete": len(el), "dissent": len(el), "partial": max(0, need - 1), "none": 0}[mode]
    done = 0
    for who in el:
        if g.rng.random() < 0.3:
            stray(g, cid, stage)
        if done >= limit or stage_of(g, cid, stage)["outcome"] != E.AWAIT:
            break
        if mode == "partial" and need == 1:
            cast(g, cid, stage, who, "abstain")
        else:
            cast(g, cid, stage, who, yes if mode in ("complete", "partial") else no)
        done += 1
    if g.rng.random() < 0.4:
        stray(g, cid, stage)  # judge after the stage closed / by outsiders
    _ = c


def decision_play(g):
    req = g.pick_request(True)
    if req is None:
        return
    who, op, args = req
    cid = f"c{g.i}-{len(g.cases) + 1}"
    g.cases.append(cid)
    rec, v = g.step(who, {"kind": "propose", "case": cid, "operation": op, "args": args, "on_behalf_of": None})
    if v.status != "OK":
        return
    if g.rng.random() < 0.5:
        g.step(who, {"kind": "execute", "case": cid})  # oracle_needed
    if g.rng.random() < 0.2:
        g.step(who, {"kind": "appeal", "case": cid})  # not_decided / not_reviewable
    mode = g.rng.choices(["complete", "partial", "none", "dissent", "lapse"], weights=[34, 20, 16, 12, 18])[0]
    d = stage_of(g, cid, "decision")
    if mode == "lapse":
        oa = d["matter"]["on_absent"] if d["matter"] else "await"
        if oa != "await":
            g.env.advance(max(1, g.M.case(cid)["ptick"] + oa["after"] - g.tick() + g.rng.choice([0, 0, 1])))
        else:
            mode = "none"
    elif mode != "none" or g.rng.random() < 0.5:
        run_stage(g, cid, "decision", mode)
    post_decision(g, cid, who, mode)


def post_decision(g, cid, who, mode):
    rng = g.rng
    ex = {"kind": "execute", "case": cid}
    d = stage_of(g, cid, "decision")
    rv = d["matter"]["review"] if d["matter"] else None
    if d["outcome"] == E.AWAIT:
        g.step(who, ex)
        if rng.random() < 0.5 and mode == "partial":
            run_stage(g, cid, "decision", "complete")  # a missing judgment arrives late
            g.step(who, ex)
        return
    if rv is not None:
        g.step(who, ex)  # inside the window: not_final
        if rng.random() < 0.6:
            appeal(g, cid, who, rv)
            if E.appealed(g.M.case(cid), INF):
                run_stage(g, cid, "review", rng.choice(["complete", "dissent", "partial", "none"]))
                g.step(who, ex)
            if rng.random() < 0.3:
                g.env.advance(rv["window"] + 1)
                g.step(who, ex)
            return
        g.env.advance(max(0, d["tick"] + rv["window"] - g.tick() + rng.choice([-1, 0, 0, 1])))
        if rng.random() < 0.3:
            appeal(g, cid, who, rv)  # at / after the window edge
    g.step(who, ex)
    if rng.random() < 0.5:
        g.step(who, ex)  # stored result / case_denied again
    if rng.random() < 0.3:
        g.step(who, {"kind": "execute", "case": cid}, rid=g.rid("x"))  # new request id, same case
    if rng.random() < 0.3:
        stray(g, cid, "decision")


def appeal(g, cid, who, rv):
    c = g.M.case(cid)
    d = stage_of(g, cid, "decision")
    party = members(g, cid, "decision") or [who]
    pick = g.rng.choice([who, who, party[0], g.rng.choice(g.principals()), rv["by"] and
                         E.body_of(g.M.doc, rv["by"])["members"][0]])
    g.step(pick, {"kind": "appeal", "case": cid})
    if g.rng.random() < 0.25:
        g.step(who, {"kind": "appeal", "case": cid})  # already_appealed / window_closed
    _ = (c, d)

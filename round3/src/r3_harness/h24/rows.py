"""Evidence rows and request construction shared by the sequence and race generators."""
from __future__ import annotations

import hashlib
import json

from r3_harness.h23.goodargs import pick_args
from r3_oracle import approvals as oapp
from r3_oracle import ops_model
from r3_oracle.authority_v2 import INF, event

VIOLATIONS = ("forbidden_effect", "post_boundary_effect", "scope_amplification", "cycle_grant", "linearizability_violation",
              "authority_ack_without_commit", "unattributed_write", "writer_violation", "unlogged_write",
              "historical_mismatch", "progress_loss")
MEASURED_ONLY = ("race_refusal_ok", "explicit_reason_mismatch", "ok")
UNMEASURABLE = ("unsupported", "world_lock_timeout")
ALL_CLASSES = VIOLATIONS + MEASURED_ONLY + UNMEASURABLE


def row_of(call: dict, res: dict, depth_of: dict | None = None) -> dict:
    keep = ("n", "kind", "rid", "actor", "obo", "op", "args", "edge", "edge_id", "to", "approved", "status", "reason", "inv",
            "ret", "crash", "replay", "intent", "lat_ms", "depth")
    r = {k: call.get(k) for k in keep if call.get(k) is not None or k in ("n", "kind", "status")}
    r.update({"classes": sorted(set(res["classes"])), "seq": res["seq"], "tick": res["tick"], "committed": res["committed"],
              "must": res.get("must"), "legal_any": res.get("legal_any"), "oracle": res["oracle"]})
    return r


def input_digest(domain: str, calls: list[dict]) -> str:
    """Identity of a sequence = its concrete inputs (not what the variant answered)."""
    keys = ("kind", "rid", "actor", "obo", "op", "args", "edge", "edge_id", "to", "approved", "crash", "replay")
    body = json.dumps([domain, [{k: c.get(k) for k in keys} for c in calls]], sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def mirror_apply(env, kind: str, payload: dict, ok: bool) -> None:
    """Generator-side guess of the authority state (targeting only): apply an event the ORACLE would accept."""
    if ok:
        env._ms = getattr(env, "_ms", 0) + 1
        env.mirror = env.mirror.apply(event(env._ms, env.clock.now(), kind, payload))


def mirror_delegate(env, edge: dict) -> None:
    mirror_apply(env, "delegate", {"edge": edge}, env.mirror.issue_delegate(edge, INF, env.clock.now()).ok)


def mirror_revoke(env, actor: str, edge_id: str) -> None:
    v = env.mirror.issue_revoke(actor, edge_id, INF)
    mirror_apply(env, "revoke", {"edge_id": edge_id}, v.ok and v.reason != "already")


def scoped_args(env, ch, op: dict, root: str, scope: dict | None, tries: int = 8):
    """Args for `op` the oracle would commit for root `root`, biased into `scope` keys. -> (args, outcome kind)."""
    last = None
    for _ in range(tries):
        a = pick_args(env, op, ch, root, "commit")
        if scope is not None:
            for i in op["inputs"]:
                ent = next((e for e in scope["resources"] if i["type"] == "resource" and e["type"] == i["resource_type"]), None)
                if ent and ent["keys"] and i["name"] in a and ch.chance(0.9):
                    a[i["name"]] = ch.choice(ent["keys"])
        out = ops_model.evaluate(env.ops, env.auth, root, None, op["name"], a, env.snapshot(), env.clock.now(),
                                 frozenset(env.committed), None, approved=False)
        last = (a, out.kind)
        if out.kind == ops_model.COMMIT and out.effects:
            return last
    return last


def approver_for(env, requester: str, obo: str, op: str, args: dict) -> str | None:
    st = env.mirror.view(None)
    chain = {obo, requester} | {x["issuer"] for e in st.edges.values() if e["child"] == requester
                                for x in env.mirror.edge_path(e["id"])}
    for p in env.principals():
        if p["id"] not in chain and oapp.validate(env.ops, env.auth, p["id"], requester, op, args)[0]:
            return p["id"]
    return None

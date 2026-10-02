"""Adversarial agent calls against hidden / denied capabilities of generated surfaces, measured on a live Engine."""
from __future__ import annotations

import random

from eoo_toolchain.runtime import EngineClient, UnknownTool, World

from . import engine_check
from .differential import load_oracle_module

LOOKALIKE = str.maketrans({"a": "а", "e": "е", "o": "о", "c": "с"})


def meter(engine, adapters: dict) -> tuple:
    """(effect log length, canonical state hash, per-adapter call counts): what an unauthorised call must not move."""
    return (len(engine.effect_log.entries()), engine.state().state_hash(),
            tuple(sorted((str(k), len(getattr(a, "calls", ()) or ())) for k, a in adapters.items())))


def sample_inputs(ir: dict, action: dict, objs: dict) -> dict:
    ref = load_oracle_module("authority_oracle").Reference(ir)
    slots = {n: d for n, d, _l, _o in ref.ref_inputs(action)}
    out = {}
    for p in action["inputs"]:
        if p["name"] in slots:
            cands = ref.candidates(slots[p["name"]], objs)
            out[p["name"]] = cands[0][0] if cands else "missing"
        else:
            t = p["type"]
            out[p["name"]] = 1 if t == "integer" else ({} if t == "json" else "x")
    return out


def mangle(name: str, rnd: random.Random) -> str:
    forms = [name.upper(), name + " ", " " + name, "_" + name, name.replace("_", "-"), name.translate(LOOKALIKE), "../" + name,
             name + "\x00", name[:-1], name + "*", "call_" + name[4:], "get_" + name[4:], "query_" + name[4:], "list_" + name[4:],
             "propose_action", "call_function", "engine.propose", "write", "__class__", "tools", "_client", "who", name.title()]
    return rnd.choice(forms)


def attack_principal(ir, engine, adapters, surf_mod, client, plain, registered, objs, opaque, pre, rnd, n_fuzz) -> dict:
    ref = load_oracle_module("authority_oracle").Reference(ir)
    case = {"principal": plain, "registered": registered, "world": {"objects": objs, "flags": {"preregistered": pre, "fault": False}}}
    want = ref.sets(case)
    s = surf_mod.AgentSurface(client, plain, World({t: list(v) for t, v in objs.items()}, {"preregistered": pre}, view=engine.read_view()),
                              opaque, registered=registered)
    granted = {t[4:] for t in s.tools if t.startswith("act_")}
    hidden = sorted(set(ref.actions) - granted)
    m0, f0 = meter(engine, adapters), engine.fingerprint()
    row = {"principal": plain["pid"], "registered": registered, "tools_exposed": len(s.tools), "actions_granted": sorted(granted),
           "actions_hidden": hidden, "surface_equals_oracle": sorted(s.tools) == want["tools"], "direct_calls": 0, "fuzz_calls": 0,
           "unknown_tool": 0, "other_outcome": [], "attribute_leaks": 0, "backstop_calls": 0, "backstop_denied": 0, "backstop_other": []}
    for aid in hidden:  # 1. ask for each hidden action by its real tool name with valid inputs
        row["direct_calls"] += 1
        row["attribute_leaks"] += hasattr(s, "act_" + aid)
        try:
            s.call("act_" + aid, idempotency_key="adv-" + aid, **sample_inputs(ir, ref.actions[aid], objs))
            row["other_outcome"].append(f"act_{aid}: call returned")
        except UnknownTool:
            row["unknown_tool"] += 1
        except Exception as exc:  # noqa: BLE001
            row["other_outcome"].append(f"act_{aid}: {type(exc).__name__}")
    base = [f"act_{a}" for a in sorted(ref.actions)] or ["act_x"]
    for _ in range(n_fuzz):  # 2. mangled / confused tool names
        name = mangle(rnd.choice(base), rnd)
        if name in s.tools:
            continue
        row["fuzz_calls"] += 1
        try:
            s.call(name, idempotency_key="adv-fuzz")
            row["other_outcome"].append(f"{name!r}: call returned")
        except UnknownTool:
            row["unknown_tool"] += 1
        except Exception as exc:  # noqa: BLE001
            row["other_outcome"].append(f"{name!r}: {type(exc).__name__}")
    row["engine_untouched_by_surface_attacks"] = (meter(engine, adapters), engine.fingerprint()) == (m0, f0)
    m1 = meter(engine, adapters)
    for aid in hidden:  # 3. backstop: bypass the surface and hit the Engine directly; the Engine's own gates must still refuse
        row["backstop_calls"] += 1
        try:
            rec = engine.propose(aid, sample_inputs(ir, ref.actions[aid], objs), plain["pid"], idempotency_key=f"adv-bs-{plain['pid']}-{aid}")
            (row.__setitem__("backstop_denied", row["backstop_denied"] + 1) if rec["state"] == "DENIED"
             else row["backstop_other"].append(f"{aid}: {rec['state']}"))
        except Exception as exc:  # noqa: BLE001 - an Engine refusal (unknown principal etc.) is a refusal
            row["backstop_denied"] += 1
    row["effects_after_backstop"] = meter(engine, adapters) != m1
    row["effects_total"] = (meter(engine, adapters) != m0)
    return row


def positive_control(ir, engine, adapters, surf_mod, client, plain, objs, opaque, pre, tries: list) -> dict:
    """An authorised call that SHOULD change something: proves the effect meter can see effects."""
    s = surf_mod.AgentSurface(client, plain, World({t: list(v) for t, v in objs.items()}, {"preregistered": pre}, view=engine.read_view()), opaque)
    m0 = meter(engine, adapters)
    for i, (tool, kw) in enumerate(tries):
        if tool not in s.tools:
            continue
        try:
            rec = s.call(tool, idempotency_key=f"adv-pos-{i}", **kw)
        except Exception as exc:  # noqa: BLE001
            continue
        if meter(engine, adapters) != m0:
            return {"principal": plain["pid"], "tool": tool, "state": rec["state"], "effect_observed": True}
    return {"principal": plain["pid"], "tool": None, "state": None, "effect_observed": False}


def run(domain: str, ir: dict, surf_mod, engine, adapters: dict, seed: int, n_fuzz: int, positive_tries: list, positive_pid: str) -> dict:
    client = EngineClient(engine)
    objs = {o["id"]: [r["key"] for r in engine.read_view().list(o["id"])] for o in ir["object_types"]}
    ops = engine_check.real_opaque(engine)
    pre = engine_check.prereg_keys(engine, ops, objs)
    rnd = random.Random(seed)
    rows = []
    for pid in sorted(engine.directory):
        rows.append(attack_principal(ir, engine, adapters, surf_mod, client, client.principal_plain(pid), True, objs, ops, pre, rnd, n_fuzz))
    ghost = {"pid": "ghost-unregistered", "roles": ["researcher", "planner"], "relations": [[t, k, r] for t in objs for k in objs[t][:1]
             for r in ("planner", "junior_planner", "agent_grant")], "delegated_by": None}
    rows.append(attack_principal(ir, engine, adapters, surf_mod, client, ghost, False, objs, ops, pre, rnd, n_fuzz))
    pos = positive_control(ir, engine, adapters, surf_mod, client, client.principal_plain(positive_pid), objs, ops, pre, positive_tries)
    tot = lambda k: sum(r[k] for r in rows)  # noqa: E731
    return {"domain": domain, "principals": rows, "positive_control": pos,
            "totals": {"principals": len(rows), "hidden_action_instances": sum(len(r["actions_hidden"]) for r in rows),
                       "direct_calls": tot("direct_calls"), "fuzz_calls": tot("fuzz_calls"), "unknown_tool": tot("unknown_tool"),
                       "attribute_leaks": tot("attribute_leaks"), "backstop_calls": tot("backstop_calls"), "backstop_denied": tot("backstop_denied"),
                       "other_outcomes": sum(len(r["other_outcome"]) + len(r["backstop_other"]) for r in rows),
                       "principals_with_effects": sum(1 for r in rows if r["effects_total"]),
                       "surface_oracle_tool_mismatches": sum(1 for r in rows if not r["surface_equals_oracle"]),
                       "engine_touched_by_surface_attacks": sum(1 for r in rows if not r["engine_untouched_by_surface_attacks"])}}

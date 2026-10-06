"""Attack rules. gen_step(env, ch, attacker) -> concrete JSON-able step; exe(env, step) -> call records.

Steps are fully concrete so a sequence replays (and shrinks) without any RNG. The attacker holds exactly one agent
identity (its own valid token); tokens of other principals are never obtainable except through the hostile forgeries
in tokens.py, which must fail.
"""
from __future__ import annotations

import copy

from r3_oracle import authority

from . import approval_rules, authspecs, crash_appr, crash_rules, tokens
from .flipdict import FlipDict
from .goodargs import pick_args

WEIGHTS = {"legit": 3, "hidden": 2, "ident": 2, "obo": 2, "retarget": 3, "mutate_body": 1, "replay": 1,
           "replay_revoke": 1, "badtoken": 2, "toctou": 2,
           **{r: 1 for r in approval_rules.RULES}, **{r: 1 for r in crash_rules.RULES}, **{r: 1 for r in crash_appr.RULES}}
IDENT_KEYS = ["principal", "actor", "owner", "requested_by", "user", "subject", "sub", "on_behalf_of", "created_by"]


def _ops(env) -> dict[str, dict]:
    return {o["name"]: o for o in env.ops["operations"]}


def _victim(env, ch, attacker: str) -> str:
    others = [p["id"] for p in env.principals() if p["id"] != attacker]
    admin = next(p["id"] for p in env.principals() if "admin" in p["roles"])
    return ch.choice(others + [admin, admin])


def _rid(env, tag: str) -> str:
    return f"rq-{env.tag}-{env.n}-{tag}"


def _mutate_args(args: dict, op: dict, snap: dict, ch) -> dict:
    a = copy.deepcopy(args)
    inputs = op["inputs"]
    i = ch.choice(inputs)
    n, t = i["name"], i["type"]
    if t == "resource":
        keys = [k.split(":", 1)[1] for k in snap["objects"] if k.startswith(i["resource_type"] + ":")]
        a[n] = ch.choice(keys + ["NOPE", "", "WH-A;DROP"])
    elif t == "integer":
        a[n] = ch.choice([-1, 0, 10 ** 9, True, 2.5, "7", None])
    elif t == "string":
        a[n] = ch.choice(["", "ephemeral:evil", " ", "x" * 200, 5])
    else:
        a[n] = ch.choice([None, [], {"min": -1}])
    if ch.chance(0.2) and i["required"]:
        a.pop(n, None)
    return a


def gen_step(env, ch, attacker: str, rule: str | None = None) -> dict:
    rule = rule or ch.choice([r for r, w in WEIGHTS.items() for _ in range(w)])
    if rule in approval_rules.RULES:
        step = approval_rules.gen_step(env, ch, attacker, rule)
        if step is not None:
            return step
        rule = "legit"  # no approval-needing request in this domain/for this attacker
    if rule in crash_appr.RULES:
        step = crash_appr.gen_step(env, ch, attacker, rule)
        if step is not None:
            return step
        rule = "legit"  # no approval-needing request, or approvals outstanding
    if rule in crash_rules.RULES:
        step = crash_rules.gen_step(env, ch, attacker, rule)
        if step is not None:
            return step
        rule = "legit"  # nothing to crash on (no committing request, or approvals outstanding)
    ops = _ops(env)
    mine = env.authorized_ops(attacker) or list(ops)
    allowed_hidden = [o for o in ops if o not in env.tools(attacker)] or list(ops)
    step = {"rule": rule, "attacker": attacker, "via": ch.choice(["call_tool", "direct"]), "obo": None,
            "tok": {"kind": "valid", "sub": attacker}, "extra": {}}
    if rule in ("legit", "replay", "replay_revoke", "mutate_body"):
        step["op"] = ch.choice(mine)
        step["via"] = "call_tool" if ch.chance(0.7) else "direct"
        dele = [d for d in env.auth["delegations"] if d["agent"] == attacker and step["op"] in d["operations"]]
        if rule == "legit" and dele and ch.chance(0.5):
            step["obo"] = ch.choice(dele)["on_behalf_of"]
        step["args"] = pick_args(env, ops[step["op"]], ch, attacker, "commit", step["obo"])
        if rule == "mutate_body":
            step["extra"]["mut"] = ch.randint(1, 3)
        if rule == "replay":
            step["extra"]["alt"] = _mutate_args(step["args"], ops[step["op"]], env.snapshot(), ch)
    elif rule == "hidden":
        step["op"] = ch.choice(allowed_hidden)
        step["via"] = "direct" if ch.chance(0.7) else "call_tool"
        step["args"] = pick_args(env, ops[step["op"]], ch, _victim(env, ch, attacker), "commit")
    elif rule in ("ident", "obo", "badtoken"):
        victim = _victim(env, ch, attacker)
        step["op"] = ch.choice(list(ops))
        step["args"] = pick_args(env, ops[step["op"]], ch, victim, "commit", None)
        if rule == "ident":
            step["extra"]["inject"] = {k: victim for k in ch.choice([IDENT_KEYS[:1], IDENT_KEYS[1:4], IDENT_KEYS])}
        elif rule == "obo":
            real = [d for d in env.auth["delegations"] if d["agent"] == attacker]
            step["obo"] = (ch.choice(real)["on_behalf_of"] if real and ch.chance(0.5) else victim)
        else:
            kinds = [k for k in tokens.KINDS if k != "expired" or env.clock.now() < 3]
            step["extra"] = {"kind": ch.choice(kinds), "victim": victim}
    elif rule == "retarget":
        step["op"] = ch.choice(list(ops))
        base = pick_args(env, ops[step["op"]], ch, attacker, "commit")
        step["args"] = _mutate_args(base, ops[step["op"]], env.snapshot(), ch)
    elif rule == "toctou":
        step["op"] = ch.choice(mine)
        benign = pick_args(env, ops[step["op"]], ch, attacker, "commit")
        hostile = _mutate_args(benign, ops[step["op"]], env.snapshot(), ch)
        step["args"], step["extra"] = benign, {"hostile": {k: v for k, v in hostile.items() if benign.get(k) != v}}
    return step


def _both(env, step, args, *, token, subject, tags, clean=False, tag="a", args_for_oracle=None, obo=None):
    """Make the call on the chosen surface; when call_tool denies/fails, repeat it on `direct` (backstop probe)."""
    recs = [env.call(rule=step["rule"], via=step["via"], token=token, subject=subject, operation=step["op"],
                     args=args, on_behalf_of=obo, request_id=_rid(env, tag), tags=tags, clean=clean,
                     args_for_oracle=args_for_oracle)]
    if step["via"] == "call_tool" and (recs[0]["status"] != "OK" or recs[0]["in_tools"] is False):
        recs.append(env.call(rule=step["rule"] + "+backstop", via="direct", token=token, subject=subject,
                             operation=step["op"], args=copy.deepcopy(args) if not isinstance(args, FlipDict)
                             else dict(args), on_behalf_of=obo, request_id=_rid(env, tag + "d"), tags=tags,
                             backstop_probe=True, args_for_oracle=args_for_oracle))
    return recs


def _mutate_body(x, k):
    if isinstance(x, dict):
        for key in list(x):
            x[key] = _mutate_body(x[key], k)
        return x
    if isinstance(x, list):
        x.append("injected")
        return [_mutate_body(i, k) for i in x]
    if isinstance(x, bool):
        return not x
    if isinstance(x, int):
        return x + 1000 * k
    return str(x) + "!x" * k


def exe(env, step: dict) -> list[dict]:  # noqa: C901
    a, rule, tok = step["attacker"], step["rule"], env.token(step["attacker"])
    if rule in approval_rules.RULES:
        return approval_rules.exe(env, step)
    if rule in crash_appr.RULES:
        return crash_appr.exe(env, step)
    if rule in crash_rules.RULES:
        return crash_rules.exe(env, step)
    args, obo = copy.deepcopy(step["args"]), step["obo"]
    if rule == "legit":
        return _both(env, step, args, token=tok, subject=a, tags=(), clean=True, obo=obo)
    if rule == "hidden":
        return _both(env, step, args, token=tok, subject=a, tags=())
    if rule == "ident":
        inj = dict(args, **step["extra"]["inject"])
        return _both(env, step, inj, token=tok, subject=a, tags={"identity"})
    if rule == "obo":
        return _both(env, step, args, token=tok, subject=a, tags={"obo"}, obo=obo)
    if rule == "retarget":
        return _both(env, step, args, token=tok, subject=a, tags=())
    if rule == "badtoken":
        t, subj = tokens.make(env, step["extra"]["kind"], step["extra"]["victim"])
        return _both(env, step, args, token=t, subject=subj, tags={"token"})
    if rule == "toctou":
        fd = FlipDict(args, step["extra"]["hostile"])
        return _both(env, step, fd, token=tok, subject=a, tags={"toctou"}, args_for_oracle=args)
    recs = [env.call(rule=rule, via=step["via"], token=tok, subject=a, operation=step["op"], args=args,
                     on_behalf_of=obo, request_id=(first := _rid(env, "1")), tags=(), clean=True)]
    if rule == "replay":
        again = [("same", args), ("alt-args", step["extra"]["alt"])]
        for lbl, ar in again:
            recs.append(env.call(rule="replay:" + lbl, via=step["via"], token=tok, subject=a, operation=step["op"],
                                 args=copy.deepcopy(ar), on_behalf_of=obo, request_id=first, tags=()))
    elif rule == "mutate_body":
        res = env.last_result
        if res is not None:
            _mutate_body(res.body, step["extra"]["mut"])  # in place: exposes variants that share returned state
        for k in list(args):  # and the caller-held args object that was passed in
            if not isinstance(args[k], str):
                args[k] = _mutate_body(args[k], 1)
        recs.append(env.call(rule="mutate_body:resubmit", via=step["via"], token=tok, subject=a,
                             operation=step["op"], args=copy.deepcopy(step["args"]), on_behalf_of=obo,
                             request_id=first, tags=()))
        recs.append(env.call(rule="mutate_body:followup", via=step["via"], token=tok, subject=a,
                             operation=step["op"], args=copy.deepcopy(step["args"]), on_behalf_of=obo,
                             request_id=_rid(env, "2"), tags=()))
    elif rule == "replay_revoke":
        env.set_authority(authspecs.revoked(env.auth, a, step["op"], env.ops))
        tok = env.token(a)
        for lbl, rid in (("same-id", first), ("fresh-id", _rid(env, "3"))):
            recs.append(env.call(rule="replay_revoke:" + lbl, via=step["via"], token=tok, subject=a,
                                 operation=step["op"], args=copy.deepcopy(step["args"]), on_behalf_of=obo,
                                 request_id=rid, tags=()))
    return recs

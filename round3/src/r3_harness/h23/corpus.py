"""Seeded corpus driver: every sequence is recorded concretely (replayable, hashable, countable as unique).

Sequence kinds: `coverage` (every principal x every operation x both surfaces, deterministic) and `attack`
(random attacker agent, 3-8 rule steps). One fresh deployment per sequence.
"""
from __future__ import annotations

import hashlib
import json
import random

from r3_oracle import authority
from r3_shared.opsspec import load_ops_spec
from r3_shared.authspec import load_auth_spec

from .chooser import RandChooser
from .env import Env
from .goodargs import pick_args
from .rules import WEIGHTS, exe, gen_step

DOMAINS = ("manufacturing", "project")
A_CLASS = {"A2": ("ident", "obo", "badtoken"), "A8": ("replay", "replay_revoke", "toctou", "mutate_body", "crash_before", "crash_after", "crash_idle", "crash_appr_before", "crash_appr_after")}


def load_specs() -> dict:
    return {d: (load_ops_spec(d), load_auth_spec(d)) for d in DOMAINS}


def seq_hash(domain: str, attacker: str, steps: list) -> str:
    body = json.dumps([domain, attacker, steps], sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def coverage_steps(env: Env, principal: str) -> list[dict]:
    ch = RandChooser(random.Random(f"cov-{env.domain}-{principal}"))
    steps = []
    mine = set(env.authorized_ops(principal))
    for o in env.ops["operations"]:
        for via in ("call_tool", "direct"):
            rule = "legit" if o["name"] in mine else "hidden"
            args = pick_args(env, o, ch, principal, "commit")
            steps.append({"rule": rule, "attacker": principal, "via": via, "obo": None, "op": o["name"],
                          "args": args, "tok": {"kind": "valid", "sub": principal}, "extra": {}})
    return steps


def run_steps(env: Env, steps: list[dict]) -> list[dict]:
    calls: list[dict] = []
    for st in steps:
        calls += exe(env, st)
    return calls


def new_env(variant, domain: str, specs: dict, tag: str) -> Env:
    ops, auth = specs[domain]
    return Env(variant, domain, ops, auth, tag)


def attack_sequence(variant, specs, seed: int, i: int, rules: list[str] | None = None):
    domain = DOMAINS[i % len(DOMAINS)]
    env = new_env(variant, domain, specs, f"{seed}-{i}")
    try:
        ch = RandChooser(random.Random(seed * 1_000_003 + i))
        agents = env.agents()
        attacker = agents[(i // len(DOMAINS)) % len(agents)]
        steps, calls = [], []
        v0 = env.dep.authority_version()
        for _ in range(ch.randint(3, 8)):
            rule = ch.choice([r for r, w in WEIGHTS.items() for _ in range(w)]) if rules is None else ch.choice(rules)
            st = gen_step(env, ch, attacker, rule)
            steps.append(st)
            calls += exe(env, st)
        return {"seq_id": f"{seed}-{i}", "kind": "attack", "domain": domain, "attacker": attacker, "steps": steps,
                "calls": calls, "hash": seq_hash(domain, attacker, steps),
                "authority_version": {"initial": v0, "final": env.dep.authority_version(),
                                      "changes": env.authority_log}}
    finally:
        env.close()


def coverage_sequences(variant, specs):
    for domain in DOMAINS:
        probe = new_env(variant, domain, specs, f"cov-{domain}")
        principals = [p["id"] for p in probe.principals()] + ["ghost-9"]
        probe.close()
        for principal in principals:
            env = new_env(variant, domain, specs, f"cov-{domain}-{principal}")
            try:
                steps = coverage_steps(env, principal) if principal != "ghost-9" else []
                calls = run_steps(env, steps)
                yield {"seq_id": f"cov-{domain}-{principal}", "kind": "coverage", "domain": domain,
                       "attacker": principal, "steps": steps, "calls": calls,
                       "hash": seq_hash(domain, principal, steps)}
            finally:
                env.close()


def crash_coverage(variant, specs):
    """Deterministic crash coverage (A8 + R-6): per domain, per agent, each crash rule (plain and with an outstanding
    approval) once, seeded with fixed retries, so the required labels never depend on the random draw."""
    from . import crash_appr, crash_rules
    for domain in DOMAINS:
        probe = new_env(variant, domain, specs, f"capp-{domain}")
        agents = probe.agents()
        probe.close()
        for agent in agents:
            for rule in crash_appr.RULES + crash_rules.RULES:
                env = new_env(variant, domain, specs, f"capp-{domain}-{agent}-{rule}")
                try:
                    for k in range(16):  # arg draws are random: a fixed number of seeded retries, same every run
                        st = gen_step(env, RandChooser(random.Random(f"capp-{domain}-{agent}-{rule}-{k}")), agent, rule)
                        if st["rule"] == rule:
                            break
                    else:
                        continue
                    calls = exe(env, st)
                    yield {"seq_id": f"capp-{domain}-{agent}-{rule}", "kind": "coverage", "domain": domain,
                           "attacker": agent, "steps": [st], "calls": calls, "hash": seq_hash(domain, agent, [st])}
                finally:
                    env.close()


def run_corpus(variant, specs, n_unique: int, seed: int, rules=None, cap_factor: int = 3, coverage: bool = True):
    """Yields sequence records until n_unique distinct hashes were produced (or cap_factor * n_unique tried)."""
    seen: set[str] = set()
    if coverage:
        for rec in coverage_sequences(variant, specs):
            if rec["steps"] and rec["hash"] not in seen:
                seen.add(rec["hash"])
            yield rec
        for rec in crash_coverage(variant, specs):
            seen.add(rec["hash"])
            yield rec
    i = 0
    while len(seen) < n_unique and i < cap_factor * n_unique:
        rec = attack_sequence(variant, specs, seed, i, rules)
        i += 1
        rec["duplicate"] = rec["hash"] in seen
        seen.add(rec["hash"])
        yield rec


def a_class_of(rule: str) -> set[str]:
    base = rule.split(":")[0].split("+")[0]
    out = {"A1"}
    for a, rs in A_CLASS.items():
        if base in rs:
            out.add(a)
    return out


__all__ = ["run_corpus", "load_specs", "seq_hash", "attack_sequence", "authority"]

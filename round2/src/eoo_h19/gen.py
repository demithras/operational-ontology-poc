"""Scenario generator: random branch histories of governed changes written from fresh or stale bases (Hypothesis-driven randomness)."""
from __future__ import annotations

import random

from hypothesis import HealthCheck, Phase, given, seed as hseed, settings, strategies as st

from eoo_exp.util import canon, sha_text

CLASSES = ("compatible_concurrent", "conflicting_concurrent", "stale_base", "rebuild_same_commit", "historical_binding_after_change")
CLAIMS, NAMES, PATHS = ("cl-a", "cl-b", "cl-c"), ("n-a", "n-b"), ("p-a", "p-b", "p-c")


def _change(rnd: random.Random) -> dict:
    k = rnd.choices(("thr", "hyp", "cmp", "met", "newm", "newc", "lg", "le", "lnew"), (6, 4, 5, 3, 3, 2, 3, 3, 1))[0]
    if k == "thr":
        return {"e": f"obj|Threshold|t{rnd.randint(1, 3)}", "props": {"value": rnd.randint(0, 2)}}
    if k == "hyp":
        return {"e": f"obj|Hypothesis|h{rnd.randint(1, 3)}", "props": {"claim": rnd.choice(CLAIMS)}}
    if k == "cmp":
        props = rnd.choice(({"path": rnd.choice(PATHS)}, {"orphan_flagged": rnd.random() < 0.5}, {"path": rnd.choice(PATHS), "orphan_flagged": True}))
        return {"e": f"obj|Component|c{rnd.randint(1, 3)}", "props": props}
    if k == "met":
        return {"e": f"obj|Metric|m{rnd.randint(1, 3)}", "props": {"name": rnd.choice(NAMES)}}
    if k == "newm":
        return {"e": f"obj|Metric|mn{rnd.randint(0, 2)}", "props": {"name": rnd.choice(NAMES)}}
    if k == "newc":
        return {"e": f"obj|Component|cn{rnd.randint(0, 1)}", "props": {"path": rnd.choice(PATHS), "orphan_flagged": rnd.random() < 0.5}}
    if k == "lg":
        return {"e": f"lnk|GOVERNED_BY|Metric|m{rnd.randint(1, 3)}|Threshold|t{rnd.randint(1, 4)}", "props": {}}
    if k == "le":
        return {"e": f"lnk|EXISTS_FOR|Component|c{rnd.randint(1, 3)}|Hypothesis|h{rnd.randint(1, 3)}", "props": {}}
    return {"e": f"lnk|EXISTS_FOR|Component|cn{rnd.randint(0, 1)}|Hypothesis|h{rnd.randint(1, 3)}", "props": {}}  # endpoint may not exist at the base


def _props_of(rnd: random.Random, t: str) -> dict:
    if t == "Threshold":
        return {"value": rnd.randint(0, 2)}
    if t == "Hypothesis":
        return {"claim": rnd.choice(CLAIMS)}
    if t == "Metric":
        return {"name": rnd.choice(NAMES)}
    return rnd.choice(({"path": rnd.choice(PATHS)}, {"orphan_flagged": rnd.random() < 0.5}, {"path": rnd.choice(PATHS), "orphan_flagged": True}))


def _change_like(rnd: random.Random, ch: dict) -> dict:
    """A second change of the same entry as ``ch`` with its own draw of properties (the two sides agree or differ by chance)."""
    if not ch["e"].startswith("obj|"):
        return ch
    t, key = ch["e"].split("|")[1:3]
    props = {"path": rnd.choice(PATHS), "orphan_flagged": rnd.random() < 0.5} if key.startswith("cn") else _props_of(rnd, t)  # a creation needs every required property
    return {"e": ch["e"], "props": props}


def gen_scenario(rnd: random.Random) -> dict:
    mode = "never" if rnd.random() < 0.12 else "compatible"
    steps, binds = [], 0
    if rnd.random() < 0.35:  # a duel: two writers prepared on the same base touch the same entry (conflict or compatible, by value)
        ch = [_change(rnd) for _ in range(2)]
        steps += [{"k": "write", "lag": 0, "changes": [ch[0]]}, {"k": "write", "lag": 1, "changes": [_change_like(rnd, ch[0])]}]
    for _ in range(rnd.randint(1, 6)):
        r = rnd.random()
        lag = rnd.choice((1, 1, 2, 3)) if rnd.random() < 0.6 else 0
        if r < 0.14:
            steps.append({"k": "bind"})
            binds += 1
        elif r < 0.22 and binds:
            steps.append({"k": "rebind", "b": rnd.randrange(binds), "lag": lag})
        else:
            steps.append({"k": "write", "lag": lag, "changes": [_change(rnd) for _ in range(rnd.randint(1, 3))]})
    return {"mode": mode, "steps": steps}


def scenario_hash(sc: dict) -> str:
    return sha_text(canon(sc))[:20]


def generate(seed0: int, n: int) -> tuple[list, dict]:
    """>= n UNIQUE scenarios (by canonical hash). Duplicates produced by the random source are skipped and counted."""
    seen, out, dupes, batch = set(), [], 0, 0
    while len(out) < n and batch < 40:
        want = max(100, int((n - len(out)) * 1.1))

        def sink(rnd):
            nonlocal dupes
            sc = gen_scenario(rnd)
            h = scenario_hash(sc)
            if h in seen:
                dupes += 1
                return
            seen.add(h)
            out.append(sc)

        @hseed(seed0 + batch)
        @settings(max_examples=want, database=None, deadline=None, phases=[Phase.generate], suppress_health_check=list(HealthCheck))
        @given(st.randoms(use_true_random=False))
        def body(rnd):
            sink(rnd)
        body()
        batch += 1
    out = out[:n]
    return out, {"requested_unique": n, "unique_scenarios": len(out), "duplicates_skipped": dupes, "batches": batch, "seed": seed0,
                 "corpus_hash": sha_text(canon(sorted(scenario_hash(s) for s in out)))}

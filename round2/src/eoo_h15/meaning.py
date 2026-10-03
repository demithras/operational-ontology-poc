"""Meaning rule, machine check (protocol/H15_V2_PREREG.json meaning_rule): the bounded-vocabulary test.

A surface phrase is a rendered line with its atoms masked. Neither OpenPona surface writes atoms into a line (they
live in the record), so the masked phrase is the whitespace-normalised line itself. Over packages grouped by size
(resource count), the number of DISTINCT phrases must stay within the size of the surface's phrase table: a
surface that needs more distinct phrases as packages grow is enumerating (labels) and violates the rule.

The bound is the surface's phrase table counted as phrases: every row expanded over the finite alternatives of its
slots, an address/binding slot counted once per head word it allows (a label is not a phrase alternative).
"""
from __future__ import annotations

import itertools
import re

from .util import KINDS


def masked_phrases(text: str) -> list[str]:
    return [" ".join(ln.split()) for ln in text.splitlines()]


def size(ir: dict) -> int:
    return sum(len(ir.get(k, [])) for k in KINDS)


def bounded_vocabulary(render, packages: list[tuple[str, dict]], bound: int) -> dict:
    """render: IR -> (text, record). packages: [(label, IR)]. Returns per-size counts and the verdict."""
    groups: dict[int, dict] = {}
    union: set[str] = set()
    for label, ir in packages:
        ph = set(masked_phrases(render(ir)[0]))
        union |= ph
        g = groups.setdefault(size(ir), {"packages": 0, "sum": 0, "max": 0, "max_label": None, "union": set()})
        g["packages"] += 1
        g["sum"] += len(ph)
        if len(ph) > g["max"]:
            g["max"], g["max_label"] = len(ph), label
        g["union"] |= ph
    per_size, cumulative, seen = [], [], set()
    for s in sorted(groups):
        g = groups[s]
        seen |= g["union"]
        per_size.append({"size": s, "packages": g["packages"], "mean_distinct_per_package": round(g["sum"] / g["packages"], 2),
                         "max_distinct_per_package": g["max"], "max_label": g["max_label"],
                         "distinct_in_group": len(g["union"]), "cumulative_distinct_up_to_size": len(seen)})
        cumulative.append(len(seen))
    over = [r["size"] for r in per_size if r["max_distinct_per_package"] > bound or r["distinct_in_group"] > bound]
    ok = len(union) <= bound and not over
    return {"phrase_table_size": bound, "packages": len(packages), "sizes": len(per_size),
            "distinct_phrases_total": len(union), "sizes_over_bound": over, "per_size": per_size,
            "ok": ok, "verdict": "bounded" if ok else "grows_beyond_phrase_table (enumeration)"}


# ---------------------------------------------------------------- phrase-table sizes
def v2_table_size() -> int:
    from eoo_openpona2.table import table_size
    return table_size()


_V1PH = re.compile(r"\{(\w+)(?::([\w,]+))?\}")


def v1_table_size() -> int:
    """The v1 table (src/eoo_openpona/templates.py) counted the same way: each address slot = one alternative per
    head it allows (its enumerated `pi X Y` label is not a phrase), {TYPE} = primitives + typeref heads."""
    from eoo_openpona.templates import ROLES, T
    from eoo_openpona.vocab import PRIMITIVE_PHRASES

    def alts(tok: str) -> int:
        m = _V1PH.fullmatch(tok)
        if not m:
            return 1
        kind, arg = m.group(1), m.group(2)
        if kind in ("DECL", "DECL0", "S"):
            return len(arg.split(","))
        if kind == "R":
            return len(ROLES[arg])
        if kind == "TYPE":
            return len(PRIMITIVE_PHRASES) + len(ROLES["typeref"])
        return 1  # V, NI, PKG
    total = 0
    for pat, *_ in T.values():
        total += list(itertools.accumulate((alts(t) for t in pat.split()), lambda a, b: a * b))[-1]
    return total

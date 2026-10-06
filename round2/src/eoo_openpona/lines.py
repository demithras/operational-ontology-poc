"""One line -> (template id, slot values). Fails closed on anything the pinned parser does not
read as exactly the structure the template assumes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from openpona.parser import parse

from .errors import Ambiguous, Invalid
from .templates import ROLES, T
from .vocab import PARTICLES, PHRASE_PRIMITIVE, PRIMITIVE_PHRASES

_PH = re.compile(r"\{(\w+)(?::([\w,]+))?\}")
BINDING = ("pkg", "decl", "val", "ni")  # placeholder kinds that consume an atom slot


@lru_cache(maxsize=None)
def compiled(tid: str) -> tuple:
    items = []
    for tok in T[tid][0].split():
        m = _PH.fullmatch(tok)
        if not m:
            items.append(("lit", tok))
            continue
        kind, arg = m.group(1).lower(), m.group(2)
        if kind in ("decl", "decl0", "s"):
            items.append(({"s": "subj"}.get(kind, kind), tuple(arg.split(","))))
        elif kind == "r":
            items.append(("ref", ROLES[arg], arg))
        elif kind == "v":
            items.append(("val", arg))
        else:
            items.append((kind,))
    return tuple(items)


def n_slots(tid: str) -> int:
    return sum(1 for it in compiled(tid) if it[0] in BINDING)


def _addr(toks, i, heads):
    n = len(toks)
    if i + 1 >= n or toks[i] not in heads or toks[i + 1] != "pi":
        return None
    j = i + 1
    while j < n and toks[j] == "pi":
        if j + 2 >= n:
            return None
        x, y = toks[j + 1], toks[j + 2]
        if x in PARTICLES or y in PARTICLES or "tan" in (x, y):
            return None
        j += 3
    return j


def _match(items, toks, k, i, acc, out):
    if k == len(items):
        if i == len(toks):
            out.append(list(acc))
        return
    it = items[k]
    kind = it[0]
    if kind == "lit":
        if i < len(toks) and toks[i] == it[1]:
            _match(items, toks, k + 1, i + 1, acc, out)
    elif kind == "pkg":
        if i < len(toks) and toks[i] == "kulupu":
            _match(items, toks, k + 1, i + 1, acc + [("pkg", "kulupu")], out)
    elif kind in ("decl", "decl0", "subj", "ref"):
        j = _addr(toks, i, it[1])
        if j is not None:
            val = (kind, " ".join(toks[i:j])) if kind != "ref" else ("ref", " ".join(toks[i:j]), it[2])
            _match(items, toks, k + 1, j, acc + [val], out)
    elif kind == "val":
        if toks[i:i + 2] == [it[1], "ni"]:
            _match(items, toks, k + 1, i + 2, acc + [("val", it[1])], out)
    elif kind == "ni":
        if toks[i:i + 1] == ["ni"]:
            _match(items, toks, k + 1, i + 1, acc + [("ni", "ni")], out)
    elif kind == "type":
        for name, ph in PRIMITIVE_PHRASES.items():
            if tuple(toks[i:i + len(ph)]) == ph:
                _match(items, toks, k + 1, i + len(ph), acc + [("type", ("prim", name))], out)
        j = _addr(toks, i, ROLES["typeref"])
        if j is not None:
            _match(items, toks, k + 1, j, acc + [("type", ("addr", " ".join(toks[i:j])))], out)
    else:  # pragma: no cover - template table error
        raise AssertionError(kind)


# ------------------------------------------------------------------ skeleton
def _expr(toks) -> str:
    parts, cur = [], []
    for t in toks:
        if t == "anu":
            parts.append(cur)
            cur = []
        else:
            cur.append(t)
    parts.append(cur)
    s = "{" + " ".join(parts[-1]) + "}"
    for p in reversed(parts[:-1]):
        s = "({" + " ".join(p) + "} anu " + s + ")"
    return s


def _split(toks, seps):
    out, cur, sep = [], [], None
    for t in toks:
        if t in seps:
            out.append((sep, cur))
            cur, sep = [], t
        else:
            cur.append(t)
    out.append((sep, cur))
    return out


def _pred(toks) -> str:
    if toks and toks[0] == "tan":
        segs = _split(toks[1:], ("tan",))
        return "tan " + _expr(segs[0][1]) + "".join(f" tan {_expr(c)}" for _, c in segs[1:])
    segs = _split(toks, ("e", "tan"))
    return _expr(segs[0][1]) + "".join(f" {s} {_expr(c)}" for s, c in segs[1:])


def expected_skeleton(toks: list[str]) -> str:
    """The parser skeleton the naive reading (every particle structural) predicts."""
    ctx = None
    if "la" in toks:
        i = toks.index("la")
        ctx, toks = toks[:i], toks[i + 1:]
    segs = _split(toks, ("li",))
    clause = _expr(segs[0][1])
    if len(segs) > 1:
        clause = "(" + clause + "".join(" li " + _pred(c) for _, c in segs[1:]) + ")"
    if ctx is None:
        return clause
    if ctx and ctx[0] == "tan":
        return f"(tan {_expr(ctx[1:])} la {clause})"
    return f"({_expr(ctx)} la {clause})"


@lru_cache(maxsize=1 << 16)
def parsed(text: str):
    """Memoised call of the unmodified pinned parser (a pure function of the line text).

    Nothing about the result is changed; callers must not mutate it."""
    return parse(text)


@dataclass(frozen=True)
class Line:
    lineno: int
    text: str
    tid: str
    slots: tuple  # placeholder values in pattern order


def read_line(lineno: int, text: str) -> Line:
    r = parsed(text)
    if r.status == "AMBIGUOUS":
        raise Ambiguous("parse_ambiguous", f"OpenPona parse is AMBIGUOUS: {r.skeletons}", lineno)
    if r.status != "RESOLVED":
        raise Invalid("parse_invalid", f"OpenPona parse is {r.status}: {r.errors}", lineno)
    toks = r.tokens
    if r.skeletons != [expected_skeleton(toks)]:
        raise Invalid("structure_mismatch", f"parser reads {r.skeletons}, encoding expects "
                      f"{expected_skeleton(toks)!r}", lineno)
    hits = []
    for tid in T:
        out: list = []
        _match(compiled(tid), toks, 0, 0, [], out)
        hits += [(tid, m) for m in out]
    if not hits:
        raise Invalid("unknown_line", f"no encoding rule matches {' '.join(toks)!r}", lineno)
    if len(hits) > 1:
        raise Ambiguous("line_ambiguous", f"several encoding rules match: {[h[0] for h in hits]}", lineno)
    return Line(lineno, " ".join(toks), hits[0][0], tuple(hits[0][1]))


def type_phrase(te_prim: str) -> list[str]:
    return list(PRIMITIVE_PHRASES[te_prim])


assert set(PHRASE_PRIMITIVE.values()) == set(PRIMITIVE_PHRASES)

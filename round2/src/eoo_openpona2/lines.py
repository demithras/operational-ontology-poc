"""One line -> (rule entry). Fails closed on anything the pinned parser does not read RESOLVED as exactly the
structure the rule assumes, and on any line that is not one of the phrase table's concrete instances."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from openpona.parser import parse

from .errors import Ambiguous, Invalid
from .table import Entry, lines


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
    """Memoised call of the unmodified pinned parser (a pure function of the line text). Callers must not mutate it."""
    return parse(text)


@dataclass(frozen=True)
class Line:
    lineno: int
    text: str
    entry: Entry

    @property
    def rid(self) -> str:
        return self.entry.rid


def n_slots(text: str) -> int:
    """Atom slots a (valid) line declares; 0 for a line outside the table."""
    e = lines().get(" ".join(text.split()))
    return e.n_atoms if e else 0


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
    norm = " ".join(toks)
    e = lines().get(norm)
    if e is None:
        raise Invalid("unknown_line", f"no phrase-table row matches {norm!r}", lineno)
    return Line(lineno, norm, e)

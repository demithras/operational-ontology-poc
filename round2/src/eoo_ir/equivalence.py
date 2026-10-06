"""Semantic equivalence of two IR packages. Operates on IR only; knows no surface syntax.

``equivalent(a, b)`` is equality of the FULLY normalized packages over every field (including
description, determinism, domain_id, metadata). That is deliberately stricter than the minimum
list in semantic-equivalence.md; see ontology/h15_oracle_notes.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .normalize import jkey, normalize


@dataclass(frozen=True)
class EquivalenceResult:
    ok: bool
    diffs: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def _short(x: Any, n: int = 70) -> str:
    s = jkey(x)
    return s if len(s) <= n else s[: n - 3] + "..."


def _list_key(a: list, b: list) -> str | None:
    """Key field ('id' or 'name') that identifies list items in both lists, if any."""
    for key in ("id", "name"):
        ok = True
        for lst in (a, b):
            vals = []
            for it in lst:
                if not (isinstance(it, dict) and isinstance(it.get(key), str)):
                    ok = False
                    break
                vals.append(it[key])
            if not ok or len(set(vals)) != len(vals):
                ok = False
                break
        if ok and (a or b):
            return key
    return None


def _diff(a: Any, b: Any, path: str, out: list[str]) -> None:
    if jkey(a) == jkey(b):
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in a:
                out.append(f"{p}: absent != {_short(b[k])}")
            elif k not in b:
                out.append(f"{p}: {_short(a[k])} != absent")
            else:
                _diff(a[k], b[k], p, out)
        return
    if isinstance(a, list) and isinstance(b, list):
        key = _list_key(a, b)
        if key is not None:
            ma = {it[key]: it for it in a}
            mb = {it[key]: it for it in b}
            for k in sorted(set(ma) | set(mb)):
                p = f"{path}[{k}]"
                if k not in ma:
                    out.append(f"{p}: absent != {_short(mb[k])}")
                elif k not in mb:
                    out.append(f"{p}: {_short(ma[k])} != absent")
                else:
                    _diff(ma[k], mb[k], p, out)
            ka, kb = [it[key] for it in a], [it[key] for it in b]
            if ka != kb and sorted(ka) == sorted(kb):  # same items, different order (order-significant list)
                out.append(f"{path}: order {_short(ka)} != {_short(kb)}")
            return
        for i in range(max(len(a), len(b))):
            p = f"{path}[{i}]"
            if i >= len(a):
                out.append(f"{p}: absent != {_short(b[i])}")
            elif i >= len(b):
                out.append(f"{p}: {_short(a[i])} != absent")
            else:
                _diff(a[i], b[i], p, out)
        return
    out.append(f"{path or '<root>'}: {_short(a)} != {_short(b)}")


def equivalent(a: Any, b: Any) -> EquivalenceResult:
    na, nb = normalize(a), normalize(b)
    if jkey(na) == jkey(nb):
        return EquivalenceResult(True, [])
    diffs: list[str] = []
    _diff(na, nb, "", diffs)
    if not diffs:  # unreachable unless _diff is wrong; never report 'equivalent' by accident
        diffs.append("<root>: normalized forms differ")
    return EquivalenceResult(False, diffs)

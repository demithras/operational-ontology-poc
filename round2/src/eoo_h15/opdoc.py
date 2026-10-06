"""Text-level helpers for the OpenPona surface (record keys, address renaming, deletion, canonical form)."""
from __future__ import annotations

import json

from eoo_openpona.vocab import ALL_HEADS


def addresses(tokens: list[str]):
    """Yield (start, end) of every address (head followed by pi groups) in a token list."""
    i = 0
    while i < len(tokens):
        if tokens[i] in ALL_HEADS and i + 1 < len(tokens) and tokens[i + 1] == "pi":
            j = i + 1
            while j < len(tokens) and tokens[j] == "pi":
                j += 3
            yield i, j
            i = j
        else:
            i += 1


def map_addresses(text: str, fn) -> str:
    out = []
    for ln in text.splitlines():
        toks = ln.split()
        for s, e in reversed(list(addresses(toks))):
            toks[s:e] = fn(" ".join(toks[s:e])).split()
        out.append(" ".join(toks))
    return "".join(x + "\n" for x in out)


def alpha_canonical(text: str) -> str:
    seen: dict[str, str] = {}
    count: dict[str, int] = {}

    def fn(a: str) -> str:
        if a not in seen:
            h = a.split()[0]
            count[h] = count.get(h, 0) + 1
            seen[a] = f"{h} #{count[h]}"
        return seen[a]

    out = []
    for ln in text.splitlines():
        toks = ln.split()
        parts, i = [], 0
        for s, e in addresses(toks):
            parts += toks[i:s] + [fn(" ".join(toks[s:e]))]
            i = e
        out.append(" ".join(parts + toks[i:]))
    return "\n".join(out)


def delete_line(text: str, rec: dict, k: int) -> tuple[str, dict]:
    """Delete line k (1-based) and renumber the record keys after it."""
    lines = text.splitlines()
    del lines[k - 1]
    out = {}
    for key, v in rec.items():
        n, slot = key[1:].split(".")
        n = int(n)
        if n == k:
            continue
        out[f"L{n - 1 if n > k else n}.{slot}"] = v
    return "".join(x + "\n" for x in lines), out


def canonical_doc(text: str, rec: dict) -> str:
    """Text + record in a normal form for 'same statements' (external-name declarations form a set; all other
    addresses are alpha-renamed by first occurrence; every line carries its atoms)."""
    lines = text.splitlines()
    atoms = {int(k[1:].split(".")[0]): v for k, v in rec.items()}
    ext_label: dict[str, tuple] = {}
    ext_lines = []
    for n, ln in enumerate(lines, 1):
        toks = ln.split()
        if toks[0] == "weka" and " li tan kulupu pi " in ln:
            s, e = next(addresses(toks))
            ext_label[" ".join(toks[s:e])] = (" ".join(toks[e + 2:]), atoms.get(n))
            ext_lines.append(n)
    body = [(n, ln) for n, ln in enumerate(lines, 1) if n not in ext_lines]
    imp_alpha = {}
    for ln in lines:
        if ln.startswith("kulupu li kute e kulupu pi "):
            imp_alpha[ln[len("kulupu li kute e "):]] = f"kulupu #{len(imp_alpha) + 1}"
    labels = {a: f"weka<{imp_alpha.get(i, i)}#{json.dumps(nm, ensure_ascii=False)}>" for a, (i, nm) in ext_label.items()}
    renamed = map_addresses("".join(ln + "\n" for _, ln in body), lambda a: labels.get(a, a))
    out = [f"{ln} || {json.dumps(atoms.get(n), ensure_ascii=False)}"
           for (n, _), ln in zip(body, alpha_canonical(renamed).splitlines())]
    return "\n".join(sorted(labels.values()) + out)

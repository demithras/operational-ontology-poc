"""Helpers for the OpenPona surface tests (H15 Phase 2)."""
from __future__ import annotations

import json
import random
from pathlib import Path

from eoo_openpona.lines import read_line
from eoo_openpona.vocab import ALL_HEADS, PAIRS

ROOT = Path(__file__).resolve().parents[2]
LITERAL_RULES = {"link.from_min", "link.from_max", "link.to_min", "link.to_max", "meta.int", "meta.float"}
ENUM_KEYS = {"operation", "decision", "effect", "severity", "idempotency", "determinism", "purity", "truth_status"}
TYPE_KEYS = {"type", "output", "list", "optional"}
PRIMS = {"string", "integer", "number", "boolean", "datetime", "date", "json", "bytes"}


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def slot_rules(text: str) -> dict[str, str]:
    """record key -> rule id of the line that declares that slot."""
    out = {}
    for i, ln in enumerate(text.splitlines(), 1):
        tid = read_line(i, ln).tid
        out[f"L{i}.a1"] = tid
    return out


def rename_atoms(text: str, rec: dict, fresh) -> dict:
    """Replace every non-literal atom by fresh(key); literal (numeric) atoms are kept."""
    rules = slot_rules(text)
    return {k: (v if rules[k] in LITERAL_RULES else fresh(k)) for k, v in rec.items()}


def numeric_placeholders(text: str, rec: dict) -> dict:
    rules = slot_rules(text)
    ph = {"meta.float": "1.5"}
    return {k: (ph.get(rules[k], "1") if rules[k] in LITERAL_RULES else k) for k in rec}


def shape(x, key: str = "", meta: bool = False):
    """IR with every atom-derived string replaced by '·' and every number by '#'.

    Metadata objects become [['·', value], ...] lists (their keys are atoms, so they would collide)."""
    if isinstance(x, dict):
        if meta:
            return [["·", shape(v, meta=True)] for v in x.values()]
        return {k: shape(v, k, meta=(k == "metadata")) for k, v in x.items()}
    if isinstance(x, list):
        return [shape(v, key, meta) for v in x]
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, (int, float)):
        return "#"
    if not meta and (key in ENUM_KEYS or (key in TYPE_KEYS and x in PRIMS)):
        return x
    return "·"


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
        spans = list(addresses(toks))
        for s, e in reversed(spans):
            toks[s:e] = fn(" ".join(toks[s:e])).split()
        out.append(" ".join(toks))
    return "".join(x + "\n" for x in out)


def alpha_canonical(text: str) -> str:
    """Rename addresses by order of first occurrence per head (alpha-equivalence normal form)."""
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
        spans = list(addresses(toks))
        parts, i = [], 0
        for s, e in spans:
            parts += toks[i:s] + [fn(" ".join(toks[s:e]))]
            i = e
        out.append(" ".join(parts + toks[i:]))
    return "\n".join(out)


def random_address_bijection(text: str, seed: int):
    """A random injective renaming of every address in text (same head, fresh pi groups)."""
    rng = random.Random(seed)
    addrs = sorted({" ".join(ln.split()[s:e]) for ln in text.splitlines() for s, e in addresses(ln.split())})
    used, mapping = set(), {}
    for a in addrs:
        while True:
            groups = rng.randint(1, 2)
            new = " ".join([a.split()[0]] + [w for _ in range(groups) for w in ("pi", *rng.choice(PAIRS))])
            if new not in used:
                used.add(new)
                mapping[a] = new
                break
    return mapping


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
    """Text + record in a normal form for 'same statements': every line carries its atom; external-name
    declarations (a set, emitted in first-use order) are sorted and their addresses are labelled by
    (import address, name atom); all other addresses are alpha-renamed by first occurrence."""
    lines = text.splitlines()
    atoms = {int(k[1:].split(".")[0]): v for k, v in rec.items()}
    ext_label: dict[str, str] = {}
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

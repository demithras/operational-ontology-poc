"""OpenPona vocabulary used by the H15 encoding: kind heads, primitive type phrases, addresses.

Nothing here is a new token: every word is one of the 42 tokens at the pinned commit.
Glosses that justify each choice live in ``templates.py`` / ontology/openpona_encoding.md.
"""
from __future__ import annotations

from openpona import SEMANTIC

PARTICLES = ("li", "la", "e", "pi", "anu")

# Address head word -> what the address stands for.
RESOURCE_HEADS = {
    "ijo": "object_types",       # ijo: reify; entity/thing
    "linja": "link_types",       # linja: link; thread; chain
    "selo": "interfaces",        # selo: boundary; surface; enclosure/interface
    "ilo": "functions",          # ilo: instrument; tool; means
    "pali": "actions",           # pali: execute; work; make
    "lawa": "policies",          # lawa: govern; regulate; control
    "ken": "authority_rules",    # ken: possibility; enablement; permission-capability
    "lukin": "observation_types",  # lukin: inspect; intentionally observe
    "awen": "constraints",       # awen: retain; persist; hold (an invariant that holds)
}
KIND_HEAD = {v: k for k, v in RESOURCE_HEADS.items()}
OTHER_HEADS = {
    "kulupu": "import",          # kulupu: group; aggregate (another package)
    "weka": "external",          # weka: remove; distance; "away" (a name outside this package)
    "sona": "property",          # sona: know; model (what is modelled about an entity)
    "kute": "parameter",         # kute: receive; accept a signal (an input received)
    "ante": "effect",            # ante: difference; transformation (a change)
    "nasin": "type_node",        # nasin: route; method; "way" (the way a value is shaped)
    "sitelen": "meta_node",      # sitelen: represent; encode; inscribe (a metadata value)
}
ALL_HEADS = {**RESOURCE_HEADS, **OTHER_HEADS}

# Primitive type -> phrase (tuple of tokens). boolean contains `anu` (an expression of two phrases).
PRIMITIVE_PHRASES = {
    "string": ("sitelen", "toki"),
    "integer": ("kulupu", "ijo"),
    "number": ("kulupu", "pilin"),
    "boolean": ("lon", "anu", "ala"),
    "datetime": ("tenpo",),
    "date": ("tenpo", "sike"),
    "json": ("sitelen", "kulupu"),
    "bytes": ("sitelen", "sijelo"),
}
PHRASE_PRIMITIVE = {v: k for k, v in PRIMITIVE_PHRASES.items()}

# Distinguisher pool for addresses: every semantic token except the dual token `tan`
# (SEMANTIC already excludes the six structural tokens).
POOL = tuple(t for t in SEMANTIC if t != "tan")
PAIRS = tuple((x, y) for x in POOL for y in POOL if x != y)
assert len(POOL) == 36 and len(PAIRS) == 1260


def distinguisher(n: int) -> list[str]:
    """n-th distinguisher (n >= 0) as a token list 'pi X Y [pi X Y ...]' (bijective base-1260).

    The tokens carry no value: the compiler only ever compares whole addresses for equality,
    and tests/h15/test_openpona_roundtrip.py checks that any bijective renaming of addresses
    compiles to the identical IR.
    """
    if n < 0:
        raise ValueError(n)
    b = len(PAIRS)
    k = 1
    while n >= b ** k:
        n -= b ** k
        k += 1
    digits = []
    for _ in range(k):
        digits.append(n % b)
        n //= b
    out: list[str] = []
    for d in reversed(digits):
        out += ["pi", *PAIRS[d]]
    return out


def address(head: str, n: int) -> str:
    return " ".join([head, *distinguisher(n)])

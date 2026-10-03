"""OpenPona v2 vocabulary: kind heads, primitive type phrases, reference roles.

Nothing here is a new token: every word is one of the 42 tokens at the pinned commit. There is no address
enumeration: a thing is written as its kind head followed by `ni` ("this <head>, bound in the record"),
and the record atom bound to that `ni` is the thing's identifier (H15 v2 prereg, amended sidecar boundary).
"""
from __future__ import annotations

PARTICLES = ("li", "la", "e", "pi", "anu")

# Head word -> resource array it names (the kind of the bound thing).
RESOURCE_HEADS = {
    "ijo": "object_types",       # ijo: reify; entity/thing
    "linja": "link_types",       # linja: link; thread; chain
    "selo": "interfaces",        # selo: boundary; surface; interface
    "ilo": "functions",          # ilo: instrument; tool; means
    "pali": "actions",           # pali: execute; work; make
    "lawa": "policies",          # lawa: govern; regulate
    "ken": "authority_rules",    # ken: possibility; enablement; permission-capability
    "lukin": "observation_types",  # lukin: inspect; observe
    "awen": "constraints",       # awen: retain; persist; hold (an invariant that holds)
}
KIND_HEAD = {v: k for k, v in RESOURCE_HEADS.items()}

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

# A reference alternative is one of:
#   a head h      -> "h ni"                    (one atom: the target id; kind = RESOURCE_HEADS[h])
#   "ext"         -> "weka ni pi kulupu ni"    (two atoms: name, import string) = '<import>#<name>'
#   "prop:h"      -> "sona ni pi h ni"         (two atoms: property name, owner id) = '<owner>.<name>'
ROLES = {
    "endpoint": ("ijo", "selo", "ext"),
    "iface": ("selo", "ext"),
    "link": ("linja", "ext"),
    "object": ("ijo", "ext"),
    "object_or_link": ("ijo", "linja", "ext"),
    "action": ("pali", "ext"),
    "authority": ("ken", "ext"),
    "policy": ("lawa", "ext"),
    "readable": ("ijo", "linja", "lukin", "ext", "prop:ijo", "prop:linja", "prop:lukin"),
    "typeref": ("ijo", "selo", "ext"),
}
EXT_TOKENS = ("weka", "ni", "pi", "kulupu", "ni")

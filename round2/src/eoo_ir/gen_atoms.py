"""Hypothesis building blocks: adversarial atoms, metadata JSON, flags."""
from __future__ import annotations

from hypothesis import strategies as st

KEYWORDS = [
    "function", "action", "object_type", "link", "interface", "policy", "authority", "observation",
    "constraint", "true", "false", "null", "none", "yes", "no", "on", "off", "~", "ref", "list",
    "optional", "string", "integer", "min", "max", "*", "version", "required", "immutable", "allow",
    "deny", "effect", "id", "name", "type", "imports", "auth:x", "policy:x", "#", "x#y", "a.b", "a:b",
    "-", "--", "---", "...", "{", "}", "[", "]", "(", ")", ",", "\"", "'", "`", "\\", "$", "%", "&",
    "!", "@", "=", "=>", "->", "|", "<", ">", "?", ".", "..", "0", "123", "1.5", "-1", "1e3", "NaN",
    " ", "  lead", "trail ", "two  spaces", "line\nbreak", "tab\there", "cr\rlf", "quote\"s", "it's",
    "café üñ", "日本語", "\U0001f600", " ", " ", "á",
    "x: y", "- z", "# not a comment", "&anchor", "*alias", "!tag", "{{tmpl}}", "${var}",
]

_FIRST = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_"
_REST = _FIRST + "0123456789"
_IDENT = st.builds(lambda a, b: a + b, st.sampled_from(_FIRST), st.text(alphabet=_REST, max_size=10))
_ALPHABET = st.characters(blacklist_categories=("Cs", "Cc", "Cn"))
_FREE = st.text(alphabet=_ALPHABET, min_size=1, max_size=10)
_WS = st.text(alphabet=st.sampled_from(list("ab \n\t\"':#-")), min_size=1, max_size=8)


def atoms() -> st.SearchStrategy[str]:
    """Non-empty identifier/atom strings: plain, unicode, whitespace, quotes, keyword-like."""
    return st.one_of(_IDENT, _IDENT, _IDENT, st.sampled_from(KEYWORDS), _FREE, _WS)


def texts() -> st.SearchStrategy[str]:
    """Free text for descriptions/predicates/expressions (non-empty)."""
    return st.one_of(atoms(), st.text(alphabet=_ALPHABET, min_size=1, max_size=40))


def maybe_empty(strat: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
    """For fields whose schema type is a bare string (no minLength): the empty string is legal and occurs."""
    return st.one_of(strat, strat, strat, st.just(""))


def bools() -> st.SearchStrategy[bool]:
    return st.booleans()


def json_values(depth: int = 2) -> st.SearchStrategy:
    """Metadata values: any JSON value (finite floats), small."""
    scalar = st.one_of(
        st.none(), st.booleans(), st.integers(-5, 5),
        st.floats(allow_nan=False, allow_infinity=False, width=32), st.text(alphabet=_ALPHABET, max_size=6),
    )
    return st.recursive(
        scalar,
        lambda c: st.one_of(st.lists(c, max_size=3), st.dictionaries(atoms(), c, max_size=3)),
        max_leaves=depth * 3,
    )


def metadata() -> st.SearchStrategy[dict]:
    return st.dictionaries(atoms(), json_values(), max_size=3)

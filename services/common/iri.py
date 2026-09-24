"""SPARQL/Turtle IRI-safety helper — shared defense-in-depth for every IRI
this codebase builds from EXTERNAL/DATABASE-sourced data (a CDC row's
primary key or column value, an identity-mapping local id, a warehouse/part
id) before it is embedded, via plain Python f-string interpolation, inside
an angle-bracketed `<...>` position of a hand-built SPARQL query/update
string.

This is a DIFFERENT grammar production from services/common/sparql_escape.py's
`escape_sparql_literal` (which escapes content for a QUOTED STRING LITERAL,
`"..."`) — per the SPARQL 1.1 grammar, `IRIREF` is
`'<' ([^<>"{}|^`\\]-[#x00-#x20])* '>'`: the characters `<`, `>`, `"`, `{`,
`}`, `|`, `^`, backtick, backslash, and every control character 0x00-0x20
are ALL forbidden unescaped inside `<...>`, and none of those overlap with
what `escape_sparql_literal` escapes (backslash/quote/newline/CR/tab) in a
way that makes it safe for this position — using the literal-escaper for an
IRI (found during a security review: services/common/identity_lookup.py and
services/common/action_rdf.py both did exactly this) neither breaks nor
fully protects the IRIREF grammar.

`services/decision_service/schemas.py`'s `_ID_PATTERN`
(`^[A-Za-z0-9_-]{1,64}$`) is the PRIMARY defense for every value that
originates from a propose()/approve() HTTP request — those characters are
always IRIREF-safe by construction, so nothing reaching RDF through that
path needs this helper to be safe. This helper exists for values that
`_ID_PATTERN` never sees at all: PRIMARY KEYS AND COLUMN VALUES READ BACK
FROM THE SOURCE DATABASES via CDC (services/ingestion) — plain `TEXT`
columns with no charset constraint at the schema level. F37 (a direct
manual DB edit) and F38 (a poison message) are exactly the adversarial
inputs this closes: a crafted WMS `lot_id`/`action_execution_id` or ERP/MES
primary key containing `>`, `}`, `"`, whitespace, or control characters
could otherwise break out of an IRIREF and inject arbitrary SPARQL (e.g.
`; DROP ALL ; #`) into a hand-built DELETE/INSERT/ASK/SELECT string.
"""

from __future__ import annotations

import re
from urllib.parse import quote

# Every character IRIREF forbids unescaped, per the SPARQL 1.1 grammar:
# https://www.w3.org/TR/sparql11-query/#rIRIREF
_IRIREF_UNSAFE_CHARS = '<>"{}|^`\\'
_IRIREF_UNSAFE_RE = re.compile(
    "[" + re.escape(_IRIREF_UNSAFE_CHARS) + "\x00-\x20]"
)


def safe_iri_component(value: str) -> str:
    """Percent-encodes `value` so it can never contain an IRIREF-unsafe
    character, for use as ONE path segment of a constructed IRI (e.g. the
    `{local_id}` in `f"{BASE}/{ClassName}/{local_id}"`). Percent-encodes
    EVERY character outside the unreserved set (letters, digits, `-._~`)
    — including `/` — since this is meant for a single segment, never a
    pre-assembled path; callers still supply their own `/` separators
    around the result. Deterministic and reversible in spirit (percent-
    encoding, not a hash), so the resulting IRI stays a legible, stable
    identifier for the same input, and idempotent (encoding twice is safe,
    just less pretty) rather than lossy."""
    return quote(str(value), safe="")


def assert_safe_iri(iri: str) -> str:
    """Defense-in-depth: verifies a FULLY ASSEMBLED IRI string contains no
    IRIREF-unsafe character before it is ever f-string-interpolated inside
    `<...>`. Every call site here should already be safe via
    `safe_iri_component` on its OWN components — this catches the case
    where a caller forgot to encode a component, or a BASE constant itself
    was hand-edited to contain something unsafe. Raises ValueError (never
    silently truncates or strips) so a bug here fails loudly instead of
    quietly producing a malformed query."""
    if _IRIREF_UNSAFE_RE.search(iri):
        raise ValueError(f"IRI contains a character forbidden inside SPARQL IRIREF (<...>): {iri!r}")
    return iri

"""SPARQL string-literal escaping — shared defense-in-depth helper.

F31 (docs/experiment/spec/09_failure_and_adversarial_matrix.md: "tool
parameter injection -> MCP/action API -> normal gates re-run server-side")
covers exactly this class of bug: a caller-supplied identifier landing
unescaped inside an f-string SPARQL query. The PRIMARY defense is input
validation at the API boundary (services/decision_service/schemas.py's
`_ID_PATTERN` — every identifier the propose request accepts must match
`^[A-Za-z0-9_-]{1,64}$` before it is used ANYWHERE, so a value containing
`"`, `}`, newlines, etc. is rejected as a malformed request (F01, HTTP 422,
zero effects) long before it could reach a query. This escaper is the
SECOND layer (belt-and-suspenders) for any value that still ends up inside
a SPARQL string literal — e.g. if a future caller of this helper forgets to
validate first, or an id legitimately contains characters the identifier
regex doesn't allow (none currently do, but the helper does not assume
that).

Per the SPARQL 1.1 grammar's ECHAR production, backslash and the literal's
own delimiter must be escaped; newlines/carriage-returns/tabs are escaped
too so a multi-line injected value can never break out of the literal onto
a new query line.
"""

from __future__ import annotations

_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def escape_sparql_literal(value: str) -> str:
    """Escapes `value` for safe embedding inside a double-quoted SPARQL
    string literal (`"...".`). Callers still wrap the result in quotes
    themselves, e.g. `f'"{escape_sparql_literal(value)}"'`."""
    return "".join(_ESCAPES.get(ch, ch) for ch in value)

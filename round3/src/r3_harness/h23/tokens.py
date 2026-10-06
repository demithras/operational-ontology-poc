"""Hostile token constructors. Every kind except `ghost` must fail verification."""
from __future__ import annotations

import base64
import json

from r3_shared.identity import IdentityProvider

KINDS = ("forged_sig", "forged_body", "foreign_secret", "wrong_aud", "expired", "garbage", "ghost")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make(env, kind: str, victim: str) -> tuple[str, str | None]:
    """Returns (token, verified_subject_or_None)."""
    good = env.token(victim)
    body, sig = good.split(".")
    if kind == "forged_sig":
        return body + "." + ("0" if sig[-1] != "0" else "1") * 64, None
    if kind == "forged_body":
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        claims["sub"] = victim
        return _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()) + "." + sig[::-1], None
    if kind == "foreign_secret":
        return IdentityProvider("attacker-controlled-secret").issue(victim, env.aud, 1000, env.clock), None
    if kind == "wrong_aud":
        return env.idp.issue(victim, "someone-elses-service", 1000, env.clock), None
    if kind == "expired":
        tok = env.idp.issue(victim, env.aud, 1, env.clock)
        env.clock.advance(1)
        return tok, None
    if kind == "garbage":
        return ("", None) if victim.endswith("1") else ("not.a.token", None)
    if kind == "ghost":  # validly signed, subject unknown to the authority fixture
        return env.idp.issue("ghost-9", env.aud, 1000, env.clock), "ghost-9"
    raise KeyError(kind)

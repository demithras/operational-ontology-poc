"""Shared identity provider: HMAC-SHA256 signed tokens, verified against the logical clock.

No delegation semantics here (variant territory). Claims: sub, iat, exp, aud, jti.
Token format: base64url(canonical-json claims) + "." + hex(hmac).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from .clock import LogicalClock


class TokenError(Exception):
    """Token is malformed, forged, wrong-audience or expired."""


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: bytes, body: str) -> str:
    return hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()


class IdentityProvider:
    def __init__(self, secret: bytes | str):
        self._secret = secret.encode() if isinstance(secret, str) else bytes(secret)
        if len(self._secret) < 8:
            raise ValueError("secret too short")
        self._seq = 0

    def issue(self, sub: str, aud: str, ttl: int, clock: LogicalClock) -> str:
        if not sub or not aud or not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0:
            raise ValueError("issue needs sub, aud and a positive int ttl")
        self._seq += 1
        iat = clock.now()
        claims = {"sub": sub, "iat": iat, "exp": iat + ttl, "aud": aud, "jti": f"jti-{self._seq}"}
        body = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
        return f"{body}.{_sign(self._secret, body)}"

    def verifier(self) -> "TokenVerifier":
        return TokenVerifier(self._secret)


class TokenVerifier:
    def __init__(self, secret: bytes):
        self._secret = secret

    def claims(self, token: str, aud: str, clock: LogicalClock) -> dict:
        if not isinstance(token, str) or token.count(".") != 1:
            raise TokenError("malformed token")
        body, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(self._secret, body)):
            raise TokenError("bad signature")
        try:
            claims = json.loads(_unb64(body))
        except Exception as exc:  # noqa: BLE001
            raise TokenError("malformed claims") from exc
        if not isinstance(claims, dict) or not all(k in claims for k in ("sub", "iat", "exp", "aud", "jti")):
            raise TokenError("missing claims")
        if claims["aud"] != aud:
            raise TokenError("wrong audience")
        if not isinstance(claims["exp"], int) or clock.now() >= claims["exp"]:
            raise TokenError("expired")
        return claims

    def verify(self, token: str, aud: str, clock: LogicalClock) -> str:
        """Return the verified subject or raise TokenError."""
        return self.claims(token, aud, clock)["sub"]

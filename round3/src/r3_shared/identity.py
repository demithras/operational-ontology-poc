"""Shared identity provider: HMAC-SHA256 signed tokens, verified against the logical clock.

No delegation semantics here (variant territory). Claims: sub, iat, exp, aud, jti.
Token format: base64url(canonical-json claims) + "." + hex(hmac).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading

from .clock import LogicalClock

REVOCATION_ENV = "R3_REVOCATION_PATH"   # P1h: a verifier built WITHOUT an explicit list consults this file when the variable is set


class TokenError(Exception):
    """Token is malformed, forged, wrong-audience or expired."""


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: bytes, body: str) -> str:
    return hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()


class RevocationList:
    """P1h identity revocation list (PROT-H30 2.1): the identity service's append-only state, one canonical JSON row per line.
    revoke_subject(sub) refuses every token whose `sub` is that subject; revoke_token(jti, aud) refuses that one token. Effective
    for the NEXT verification after the row is written (no cache past the file's (mtime, size) signature, so at most 0 ticks).
    Rows: {"seq","kind":"subject"|"token","sub","jti","aud","tick","operator","reason"}; reason values are frozen below."""
    REASONS = {"subject": "revoked_subject", "token": "revoked_token"}

    def __init__(self, path):
        self.path, self._lock, self._sig, self._rows = str(path), threading.Lock(), None, []

    @classmethod
    def from_env(cls, env=None):
        p = (os.environ if env is None else env).get(REVOCATION_ENV)
        return cls(p) if p else None

    def _read(self) -> list:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return []
        sig = (st.st_mtime_ns, st.st_size)
        with self._lock:
            if sig != self._sig:
                with open(self.path, "rb") as f:
                    data = f.read()
                self._rows = [json.loads(line) for line in data.split(b"\n") if line.strip()]
                self._sig = sig
            return self._rows

    def rows(self) -> list:
        return [dict(r) for r in self._read()]

    def _append(self, row: dict) -> dict:
        with self._lock:
            row = {"seq": len(self._read_unlocked()) + 1, **row}
            line = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
            self._sig = None
        return row

    def _read_unlocked(self) -> list:
        try:
            with open(self.path, "rb") as f:
                return [line for line in f.read().split(b"\n") if line.strip()]
        except FileNotFoundError:
            return []

    def revoke_subject(self, sub: str, tick: int, operator: str = "operator") -> dict:
        if not isinstance(sub, str) or not sub:
            raise ValueError("revoke_subject needs a subject")
        return self._append({"kind": "subject", "sub": sub, "jti": "", "aud": "", "tick": tick, "operator": operator,
                             "reason": self.REASONS["subject"]})

    def revoke_token(self, sub: str, jti: str, aud: str, tick: int, operator: str = "operator") -> dict:
        if not (isinstance(jti, str) and jti and isinstance(aud, str) and aud):
            raise ValueError("revoke_token needs jti and aud")
        return self._append({"kind": "token", "sub": sub, "jti": jti, "aud": aud, "tick": tick, "operator": operator,
                             "reason": self.REASONS["token"]})

    def check(self, claims: dict) -> str:
        """The revocation reason for verified claims, or '' when not revoked."""
        for r in self._read():
            if r["kind"] == "subject" and r["sub"] == claims["sub"]:
                return r["reason"]
            if r["kind"] == "token" and r["jti"] == claims["jti"] and r["aud"] == claims["aud"]:
                return r["reason"]
        return ""


class IdentityProvider:
    def __init__(self, secret: bytes | str, revocations: "RevocationList | None" = None):
        self._secret = secret.encode() if isinstance(secret, str) else bytes(secret)
        if len(self._secret) < 8:
            raise ValueError("secret too short")
        self._seq = 0
        self.revocations = revocations

    def issue(self, sub: str, aud: str, ttl: int, clock: LogicalClock) -> str:
        if not sub or not aud or not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0:
            raise ValueError("issue needs sub, aud and a positive int ttl")
        self._seq += 1
        iat = clock.now()
        claims = {"sub": sub, "iat": iat, "exp": iat + ttl, "aud": aud, "jti": f"jti-{self._seq}"}
        body = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
        return f"{body}.{_sign(self._secret, body)}"

    def verifier(self) -> "TokenVerifier":
        return TokenVerifier(self._secret, self.revocations)

    def revoke_subject(self, sub: str, tick: int, operator: str = "operator") -> dict:
        """Library call; the authenticated operator entry point is opplane.OperatorPlane."""
        if self.revocations is None:
            raise ValueError("this provider has no revocation list")
        return self.revocations.revoke_subject(sub, tick, operator)

    def revoke_token(self, token: str, tick: int, operator: str = "operator") -> dict:
        if self.revocations is None:
            raise ValueError("this provider has no revocation list")
        c = TokenVerifier(self._secret, NO_REVOCATIONS).parse(token)   # signature + form only (expiry/revocation ignored)
        return self.revocations.revoke_token(c["sub"], c["jti"], c["aud"], tick, operator)


class NoRevocations:
    def check(self, claims: dict) -> str:
        return ""


NO_REVOCATIONS = NoRevocations()


class TokenVerifier:
    def __init__(self, secret: bytes, revocations: "RevocationList | None" = None):
        self._secret = secret
        self._revocations = revocations if revocations is not None else RevocationList.from_env()

    def parse(self, token: str) -> dict:
        """Signature and claim form only (no audience, expiry or revocation check)."""
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
        return claims

    def claims(self, token: str, aud: str, clock: LogicalClock) -> dict:
        claims = self.parse(token)
        if claims["aud"] != aud:
            raise TokenError("wrong audience")
        if not isinstance(claims["exp"], int) or clock.now() >= claims["exp"]:
            raise TokenError("expired")
        if self._revocations is not None and self._revocations.check(claims):
            raise TokenError("revoked")
        return claims

    def verify(self, token: str, aud: str, clock: LogicalClock) -> str:
        """Return the verified subject or raise TokenError."""
        return self.claims(token, aud, clock)["sub"]

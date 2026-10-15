"""P1h shared operator plane (PROT-H30 s2.1; ORACLE-AND-HARNESS-G6 s1/s5). HARNESS ONLY - variant packages never import this module.

Four operator actions, each ONE action and each recorded (action log: in memory + optional JSONL file):
  revoke_subject(subject)          identity revocation list (r3_shared.identity.RevocationList): every token of the subject is refused
  revoke_token(token)              the same list, one token (jti, aud)
  revoke_chain(root_nonce|chain_id) ExternalWorld refuses later writes with such a cap: audit reason `revoked_chain`, no effect
  quarantine_route(system, deployment) ExternalWorld refuses every write rooted for that route: `route_quarantined`; other routes open
Delegation-edge revocation (Deployment.revoke) and AuthorityService publish already exist (H24 / P1g) and are not wrapped here.

Authentication: every call needs an OPERATOR token (aud `r3-operator`, sub `operator`) issued from a secret only the harness holds; the
attacker never has one. A refused call (bad token, bad arguments) is recorded with outcome `refused` and a frozen reason, and is NOT an
operator action for cost accounting (count_actions() counts outcome `done` rows only).

Enforcement is server side and outside the plane: TokenVerifier (identity.py) consults the revocation file on every verification (so a
revocation holds for the NEXT call, 0 ticks), ExternalWorldCore._write refuses before applying an effect. With no call ever made the
shared code paths are unchanged (empty sets / no file)."""
from __future__ import annotations

import json
import os

from .clock import LogicalClock
from .extworld import ExternalClient, ExternalError
from .identity import NO_REVOCATIONS, IdentityProvider, TokenError, TokenVerifier

OPERATOR_SUB, OPERATOR_AUD = "operator", "r3-operator"
ACTIONS = ("revoke_subject", "revoke_token", "revoke_chain", "quarantine_route")
REFUSAL_REASONS = ("operator_auth_failed", "invalid_arguments", "service_unavailable")   # frozen plane reasons (recorded rows)
SERVER_REASONS = {"identity": ("revoked_subject", "revoked_token"), "external": ("revoked_chain", "route_quarantined")}  # frozen enforcement reasons


class OperatorError(Exception):
    """The operator call was refused; .reason is one of REFUSAL_REASONS."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


class OperatorPlane:
    def __init__(self, operator_secret: bytes | str, clock: LogicalClock, idp: IdentityProvider | None = None,
                 ext: ExternalClient | None = None, log_path: str | None = None):
        self._idp_op = IdentityProvider(operator_secret)
        self._verifier = TokenVerifier(self._idp_op._secret, NO_REVOCATIONS)
        self.clock, self.idp, self.ext, self.log_path = clock, idp, ext, (str(log_path) if log_path else None)
        self.rows: list[dict] = []

    # ---- operator identity -------------------------------------------------------------------------------------------
    def operator_token(self, ttl: int = 10 ** 6) -> str:
        return self._idp_op.issue(OPERATOR_SUB, OPERATOR_AUD, ttl, self.clock)

    def _record(self, action: str, args: dict, outcome: str, reason: str) -> dict:
        row = {"seq": len(self.rows) + 1, "tick": self.clock.now(), "action": action, "args": args, "outcome": outcome,
               "reason": reason, "operator": OPERATOR_SUB}
        self.rows.append(row)
        if self.log_path:
            fd = os.open(self.log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
            finally:
                os.close(fd)
        return row

    def _run(self, op_token: str, action: str, args: dict, fn):
        try:
            sub = self._verifier.verify(op_token, OPERATOR_AUD, self.clock)
            if sub != OPERATOR_SUB:
                raise TokenError("not the operator")
        except TokenError as exc:
            self._record(action, args, "refused", "operator_auth_failed")
            raise OperatorError("operator_auth_failed", str(exc)) from exc
        try:
            res = fn()
        except (ValueError, TokenError) as exc:
            self._record(action, args, "refused", "invalid_arguments")
            raise OperatorError("invalid_arguments", str(exc)) from exc
        except ExternalError as exc:     # "unreachable" = transport failure; any other text is the service refusing the arguments
            why = "service_unavailable" if "unreachable" in str(exc) else "invalid_arguments"
            self._record(action, args, "refused", why)
            raise OperatorError(why, str(exc)) from exc
        self._record(action, args, "done", "")
        return res

    # ---- the four actions --------------------------------------------------------------------------------------------
    def revoke_subject(self, op_token: str, subject: str) -> dict:
        return self._run(op_token, "revoke_subject", {"subject": subject}, lambda: self._need_idp().revoke_subject(subject, self.clock.now(), OPERATOR_SUB))

    def revoke_token(self, op_token: str, token: str) -> dict:
        """Args are recorded as (sub, jti, aud) - never the bearer token itself."""
        idp = self._need_idp()
        try:
            c = TokenVerifier(idp._secret, NO_REVOCATIONS).parse(token)
            args = {"sub": c["sub"], "jti": c["jti"], "aud": c["aud"]}
        except TokenError:
            args = {"token": "unparseable"}
        return self._run(op_token, "revoke_token", args, lambda: idp.revoke_token(token, self.clock.now(), OPERATOR_SUB))

    def revoke_chain(self, op_token: str, root_nonce: str | None = None, chain_id: str | None = None) -> int:
        args = {"root_nonce": root_nonce} if root_nonce is not None else {"chain_id": chain_id}
        return self._run(op_token, "revoke_chain", args, lambda: self._need_ext().revoke_chain(root_nonce, chain_id, OPERATOR_SUB))

    def quarantine_route(self, op_token: str, system: str, deployment: str) -> int:
        return self._run(op_token, "quarantine_route", {"system": system, "deployment": deployment},
                         lambda: self._need_ext().quarantine(system, deployment, OPERATOR_SUB))

    # ---- accounting --------------------------------------------------------------------------------------------------
    def actions(self) -> list[dict]:
        return [dict(r) for r in self.rows]

    def count_actions(self) -> int:
        return sum(1 for r in self.rows if r["outcome"] == "done")

    def _need_idp(self) -> IdentityProvider:
        if self.idp is None or self.idp.revocations is None:
            raise ValueError("no identity provider with a revocation list is attached")
        return self.idp

    def _need_ext(self) -> ExternalClient:
        if self.ext is None:
            raise ValueError("no ExternalWorld control client is attached")
        return self.ext

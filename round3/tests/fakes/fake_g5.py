"""Reference behaviour for the Gate 5 Deployment surface (fakes only; never registered): deploy(authority_source=..., resume=...),
recovery_view, dependency_status. Honest about the P1g protocol - a lease is fetched on every governed decision while AUTH is up
and a durable lease is honoured (strict upper bound) while it is down; unavailability is the frozen reply vocabulary; resume rebuilds
from the durable stores only and raises CanonicalStateLost when they are gone. No ops-spec/authority semantics (see fake_variant)."""
from __future__ import annotations

import json
from pathlib import Path

from r3_shared.authsvc import Lease, validate_lease
from r3_shared.faultplane import CanonicalStateLost, DependencyUnavailable
from r3_shared.recovery import DEP_UNAVAILABLE, validate_recovery_view
from r3_shared.variant import CallResult
from tests.fakes.fake_variant import FakeDeployment, FakeVariant

_CACHE: dict = {}   # module-level: survives a COOPERATIVE crash()/restart() in the same process, never a host kill


class FakeG5Deployment(FakeDeployment):
    survive_in_module_cache = False

    def __init__(self, domain, factory, verifier, clock, auth_spec=None, state_dir=None, history=None, anchor=None,
                 governance=None, ops_spec=None, external=None, authority_source=None, resume=False):
        if resume and ((state_dir is None and history is None) or (state_dir is not None and not Path(state_dir).exists())):
            raise CanonicalStateLost("durable state absent")
        self.authority_source, self._auth_up, self._lease = authority_source, None, None
        super().__init__(domain, factory, verifier, clock, auth_spec, state_dir, history, anchor, governance, ops_spec, external)
        self._lease = self._load_lease()

    # ---- request_id ledger: durable in the HistoryStore when one is given (H27-style runs), else in state_dir ---------------
    def _ledger(self):
        if self.history is not None:
            raw = self.history.get("meta/ledger")
            return set(json.loads(raw)) if raw else set()
        return super()._ledger()

    def _record(self, rid):
        if self.history is not None:
            self.history.put("meta/ledger", json.dumps(sorted(self._ledger() | {rid})).encode())
        else:
            super()._record(rid)

    # ---- lease handling ------------------------------------------------------------------------------------------------
    def _lease_path(self):
        return Path(self.state_dir) / "lease.json" if self.state_dir else None

    def _load_lease(self):
        if self.survive_in_module_cache:
            return _CACHE.get("lease")
        p = self._lease_path()
        return validate_lease(json.loads(p.read_text())) if p is not None and p.exists() else None

    def _store_lease(self, lease: Lease):
        self._lease = lease
        if self.survive_in_module_cache:
            _CACHE["lease"] = lease
        p = self._lease_path()
        if p is not None:
            p.write_text(json.dumps({"digest": lease.digest, "doc": lease.doc, "granted_tick": lease.granted_tick,
                                     "lease_until": lease.lease_until, "mac": lease.mac}, sort_keys=True))

    def _gate(self):
        """None when the decision may proceed under a valid lease; else the frozen unavailable reply."""
        if self.authority_source is None:
            return None
        try:
            lease = self.authority_source.client.fetch()
            self._auth_up = True
            self._store_lease(lease)
        except DependencyUnavailable:
            self._auth_up = False
            lease = self._lease
            if lease is None or not lease.valid_at(self.clock.now()):
                return CallResult("UNAVAILABLE", {"reason": DEP_UNAVAILABLE, "dependency": "AUTH"})
        self.auth_spec = lease.doc
        return None

    # ---- gated entries ---------------------------------------------------------------------------------------------------
    def direct(self, token, operation, args, on_behalf_of=None, request_id=None):
        if not self.crashed and self._sub(token) is not None:
            g = self._gate()
            if g is not None:
                return g
        return super().direct(token, operation, args, on_behalf_of, request_id)

    def read(self, token, operation, args):
        if self._sub(token) is not None:
            g = self._gate()
            if g is not None:
                return g
        return super().read(token, operation, args)

    def approve(self, token, operation, args, requester, on_behalf_of=None):
        if not self.crashed and self._sub(token) is not None:
            g = self._gate()
            if g is not None:
                return g
        return super().approve(token, operation, args, requester, on_behalf_of)

    def restart(self):
        super().restart()
        self._lease = self._load_lease()

    # ---- G5 self-reports ---------------------------------------------------------------------------------------------------
    def recovery_view(self) -> dict:
        rows = self.world._con.execute("SELECT seq, data_json FROM world_log WHERE kind='mark' AND ref='commit' ORDER BY seq").fetchall()
        committed = []
        for seq, dj in rows:
            d = json.loads(dj)
            committed.append({"request_id": d.get("request_id"), "world_seq": seq, "authority_version": d["authority_version"]})
        intents = sorted(({"request_id": i["request_id"], "effect_index": i["effect_index"], "system": i["system"], "chain_ids": 1,
                           "state": self.g4["outcomes"][f"{i['request_id']}#{i['effect_index']}"]["state"],
                           "confidence": self.g4["outcomes"][f"{i['request_id']}#{i['effect_index']}"]["confidence"]}
                          for i in self.g4["intents"]), key=lambda x: (x["request_id"], x["effect_index"]))
        l = self._report_lease()
        return validate_recovery_view({"form": "r3-recovery-1", "committed": committed, "intents": intents,
                                       "authority": {"version": None if l is None else l.digest, "lease_until": None if l is None else l.lease_until},
                                       "approvals_open": []})

    def _report_lease(self):
        """Honest: only a lease that is still valid at the current tick is reported as the authority in use."""
        return self._lease if self._lease is not None and self._lease.valid_at(self.clock.now()) else None

    def dependency_status(self) -> dict:
        return {"AUTH": "UNKNOWN" if self._auth_up is None else ("UP" if self._auth_up else "DOWN")}


class FakeStaleCacheDeployment(FakeG5Deployment):
    """Deliberately weak: keeps the authority lease in a module-level cache that a cooperative crash does not clear."""
    survive_in_module_cache = True

    def _report_lease(self):
        return self._lease   # the bug: a retained version is reported as in force, valid or not


class FakeG5Variant(FakeVariant):
    name = "fake-g5"
    deployment_class = FakeG5Deployment

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, state_dir=None, history=None, anchor=None,
               governance=None, external=None, authority_source=None, resume=False):
        return self.deployment_class(domain, world_handle_factory, verifier, clock, auth_spec, state_dir, history, anchor,
                                     governance, ops_spec, external, authority_source, resume)


class FakeStaleCacheVariant(FakeG5Variant):
    name = "fake-g5-stalecache"
    deployment_class = FakeStaleCacheDeployment

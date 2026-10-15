"""Lease-backed authority (PROT-H29 R29-0, PROTOCOL-P1g P1g-2): Paladin's OWN lease cache (not shared code; EQUIVALENCE E2).

A governed decision fetches (renews) a lease while AUTH is reachable; while AUTH is down it may decide under the last lease only
inside its validity window granted_tick <= t < lease_until (strict). The held lease lives in memory ONLY: a restarted host
holds nothing and must fetch again - a lease persisted in a store the variant cannot MAC-check is no authority (F8), and the
oracle's lease window ends at an ENGINE restart anyway. Mutants live at the real decision sites below.
"""
from __future__ import annotations

from r3_shared.authsvc import Lease, validate_lease
from r3_shared.faultplane import DependencyUnavailable

CACHE_KEY = "lease_cache"   # written ONLY by the stale_cache_after_restart mutant (a durable cache honest builds do not keep)


def _rec(lease: Lease) -> dict:
    return {"digest": lease.digest, "doc": lease.doc, "granted_tick": lease.granted_tick, "lease_until": lease.lease_until, "mac": lease.mac}


class LeaseGate:
    def __init__(self, binding, ledger, clock, mutants=frozenset(), resume: bool = False):
        self.b, self.led, self.clock, self.mut = binding, ledger, clock, frozenset(mutants)
        self.held: Lease | None = None
        self.auth_up: bool | None = None
        self.trust_cached = False
        if resume and "stale_cache_after_restart" in self.mut:   # MUTANT: resume loads the durable cache and treats it as in force
            rec = ledger.get_meta(CACHE_KEY)
            if isinstance(rec, dict):
                try:
                    self.held, self.trust_cached = validate_lease(rec), True
                except ValueError:
                    pass

    def acquire(self, now: int) -> Lease:
        """The lease a decision at tick `now` runs under. Raises DependencyUnavailable("AUTH") when there is none."""
        try:
            lease = self.b.client.fetch()
        except DependencyUnavailable:
            self.auth_up = False
            held = self.held
            if held is not None and (held.valid_at(now) or self.trust_cached or "fail_open_on_authority_outage" in self.mut):
                return held   # MUTANTS: fail_open_on_authority_outage ignores lease_until; stale_cache_after_restart trusts the cache
            raise
        self.auth_up, self.trust_cached, self.held = True, False, lease
        if "stale_cache_after_restart" in self.mut:
            self.led.put_meta(CACHE_KEY, _rec(lease))
        return lease

    def probe_view(self, now: int) -> dict:
        """RECOVERY_VIEW `authority`: the version verified by a lease valid now, else null (unverified). Pure: no I/O."""
        h = self.held
        if h is None or not (h.valid_at(now) or self.trust_cached):   # trust_cached: the stale mutant reports a retained version as in force
            return {"version": None, "lease_until": None}
        return {"version": h.digest, "lease_until": h.lease_until}

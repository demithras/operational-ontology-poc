"""One world of a pair: seeded world store + the variant's Deployment + harness-side records for the oracle.
The observer's expected answers are recomputed from the GROUND-TRUTH snapshot (WorldReader), never from the variant."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile

from r3_oracle import ops_model, provenance as pv
from r3_oracle.disclosure import Facts, low_view
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider
from r3_shared.world import WorldStore, diff

TTL = 10 ** 9


def governed(o) -> bool:
    k = o.kind
    return k in (ops_model.COMMIT, ops_model.DENIED_AUTHORITY, ops_model.DENIED_RULE, ops_model.NEEDS_APPROVAL) or \
        (k == ops_model.INVALID and o.detail.startswith("precondition"))


def decision_rec(ops, subject, obo, op, args, rid, status, reason, eff, rows, head, now) -> dict:
    """The oracle-side DecisionRec of one governed request (PROT-H27 s1 scalars with TRUE values)."""
    opd = ops_model.op_of(ops, op)
    refs = [f"{t}:{k}" for t, k in ops_model.resources_of(opd, args)] if opd else []
    commit = next((r for r in rows if r["kind"] == "mark" and r["ref"] == "commit"), None)
    seq = commit["seq"] if commit else (rows[-1]["seq"] if rows else head)
    tick = commit["tick"] if commit else now
    eff = eff if status == "OK" else []
    eff_rows = rows if (status == "OK" and rows) else []  # E-4: digest over the transaction's world_log rows, not diff rows
    sc = {"decision_id": rid, "kind": "direct", "subject": subject, "on_behalf_of": obo, "operation": op,
          "args_digest": pv.args_digest(args), "status": status, "reason": reason,
          "effect_digest": pv.effect_digest(eff_rows), "world_seq": seq, "tick": tick, "authority_path": []}
    free = bool(opd) and all(i["type"] == "resource" for i in opd["inputs"] if i["name"] in args)
    return {"id": rid, "rid": rid, "subject": subject, "on_behalf_of": obo, "approver": None, "resources": refs,
            "args_refs": refs, "args_scalar_free": free, "scalars": sc, "effects": eff, "effect_rows": eff_rows, "edge_path": []}


class PWorld:
    def __init__(self, variant, domain: str, ops: dict, auth: dict, batches: list, governance=None, tag: str = "w"):
        self.variant, self.domain, self.ops, self.auth, self.gov = variant, domain, ops, copy.deepcopy(auth), governance
        self.dir = tempfile.mkdtemp(prefix="h26-")
        self.clock = LogicalClock(0)
        self.store = WorldStore(os.path.join(self.dir, "world.db"), clock=self.clock)
        self.seed_seqs = self.store.seed(batches)  # P1e-8: before the writer allowlist exists (harness-only writer)
        self.store.writers = frozenset(w for a in auth["service_accounts"] for w in a["world_writers"])
        self.idp = IdentityProvider(f"h26-secret-{tag}")
        self.reader = self.store.reader()
        self.state_dir = os.path.join(self.dir, "state")
        os.makedirs(self.state_dir)
        import inspect
        if "governance" not in inspect.signature(type(variant).deploy).parameters:  # built for H23-H27 only
            raise NotImplementedError("not implemented yet - G3 (deploy takes no governance)")
        hist = anc = None
        sock = os.environ.get("R3_ANCHOR_SOCK")  # run_h26.sh (ruling Q10): history + anchor, state_dir then None
        if sock:
            from r3_shared.anchor import AnchorClient
            from r3_shared.histstore import HistoryStore
            hist, anc = HistoryStore(os.path.join(self.dir, "hist.db")), AnchorClient(sock)
        self.dep = variant.deploy(domain, self.store.handle_factory(), self.idp.verifier(), ops, self.auth, self.clock,
                                  state_dir=None if sock else self.state_dir, history=hist, anchor=anc, governance=governance)
        self.aud = getattr(type(variant), "audience", None)
        if not isinstance(self.aud, str) or not self.aud:
            raise RuntimeError(f"variant {type(variant).__name__} defines no class attribute `audience`")
        self._tok: dict[str, str] = {}
        self.facts = Facts()
        self.committed: set = set()
        self.canary_pool: set = set()   # canaries the generator planted (all of them, whichever fact kind)

    def token(self, sub: str) -> str:
        if sub not in self._tok:
            self._tok[sub] = self.idp.issue(sub, self.aud, TTL, self.clock)
        return self._tok[sub]

    def snapshot(self) -> dict:
        return self.reader.snapshot()

    def view(self, observer: str):
        return low_view(self.snapshot(), self.auth, observer, self.ops, self.facts)

    # -- mutating calls (also record the oracle-side DecisionRec) ----------------------------------------------
    def request(self, subject: str, op: str, args: dict, rid: str, via: str = "direct", obo=None):
        """Run a mutating request; returns (CallResult | None, exc, effects, oracle outcome)."""
        before = self.snapshot()
        outcome = ops_model.evaluate(self.ops, self.auth, subject, obo, op, args, before, self.clock.now(),
                                     frozenset(self.committed), rid)
        res = exc = None
        try:
            fn = self.dep.direct if via == "direct" else self.dep.call_tool
            res = fn(self.token(subject), op, copy.deepcopy(args), obo, rid)
        except NotImplementedError as e:
            exc = ("unsupported", str(e))
        except Exception as e:  # noqa: BLE001 - a variant exception is data
            exc = ("variant_error", type(e).__name__)
        after = self.snapshot()
        eff = diff(before, after)
        if res is not None and res.status == "OK" and eff:
            self.committed.add(rid)
        gov = res is not None and res.status in ("OK", "DENIED", "INVALID") and governed(outcome)
        if gov:
            self._record_decision(subject, obo, op, args, rid, res, eff, after["log_head"], before["log_head"])
        return res, exc, eff, outcome

    def _record_decision(self, subject, obo, op, args, rid, res, eff, head, head_before):
        rows = self.reader.log(head_before) if eff else []
        self.facts.decisions.append(decision_rec(self.ops, subject, obo, op, args, rid, res.status,
                                                 res.body.get("reason") or ("ok" if res.status == "OK" else ""), eff, rows, head, self.clock.now()))

    def close(self) -> None:
        try:
            self.reader.close()
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)

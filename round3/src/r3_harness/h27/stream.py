"""One H27 base history: world store + HistoryStore + variant Deployment, with every governed decision recorded
harness-side (expected binding computed by the ORACLE from the pre-call snapshot and the world_log, never from the
variant's envelope). Sequential only (histories are generated sequentially, PROT-H27 s1)."""
from __future__ import annotations

import copy
import os
import shutil
import sqlite3

from r3_oracle import approvals, ops_model, provenance as pv
from r3_shared.clock import LogicalClock
from r3_shared.histstore import HistoryStore, TamperView
from r3_shared.identity import IdentityProvider
from r3_shared.world import WorldStore

TTL = 10 ** 6
GOVERNED_STATUS = ("OK", "DENIED", "INVALID")


def is_governed(outcome) -> bool:
    k = outcome.kind
    if k in (ops_model.COMMIT, ops_model.DENIED_AUTHORITY, ops_model.DENIED_RULE, ops_model.NEEDS_APPROVAL):
        return True
    return k == ops_model.INVALID and outcome.detail.startswith("precondition")


def checkpoint(path: str) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()


def copy_db(src: str, dst: str) -> None:
    checkpoint(src)
    shutil.copyfile(src, dst)


class Stream:
    def __init__(self, variant, domain: str, ops: dict, auth: dict, root: str, anchor_client, tag: str = "s"):
        self.variant, self.domain, self.ops, self.anchor = variant, domain, ops, anchor_client
        self.auth = copy.deepcopy(auth)  # authority spec in force (v1 or v2 document)
        self.v2 = auth.get("spec") == "r3-authority-2"
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.world_path, self.hist_path = os.path.join(root, "world.db"), os.path.join(root, "hist.db")
        self.clock = LogicalClock(10)
        writers = {w for a in auth["service_accounts"] for w in a["world_writers"]} | {"harness-seed", "harness-refresh"} \
            | ({getattr(type(variant), "TEST_WORLD_WRITER")} if hasattr(type(variant), "TEST_WORLD_WRITER") else set())
        self.store = WorldStore(self.world_path, clock=self.clock, writers=frozenset(writers))
        h = self.store.handle("harness-seed")
        with h.transaction(tag="seed"):
            for o in ops["seed"]["objects"]:
                h.create(o["type"], o["key"], o["props"])
            for lk in ops["seed"]["links"]:
                h.link(lk["link_type"], lk["src"], lk["dst"])
        h.close()
        self.reader = self.store.reader()
        self.idp = IdentityProvider(f"h27-secret-{tag}")
        aud = getattr(type(variant), "audience", None)
        if not isinstance(aud, str) or not aud:
            raise RuntimeError(f"variant {type(variant).__name__} defines no class attribute `audience`")
        self.aud, self._tok = aud, {}
        self.layout = dict(getattr(type(variant), "HISTORY_LAYOUT", {}) or {})
        self.hist = HistoryStore(self.hist_path)
        self.view = TamperView(self.hist_path)  # read-only use here; the log stays empty until tampering
        self.dep = variant.deploy(domain, self.store.handle_factory(), self.idp.verifier(), ops, self.auth,
                                  self.clock, state_dir=None, history=self.hist, anchor=anchor_client)
        self.decisions: list[dict] = []
        self.caps: list[dict] = []
        self.revoked: list[str] = []
        self.n = 0
        self.committed: set[str] = set()
        self.approval_keys: dict[str, dict] = {}
        self.notes: list[str] = []

    # -- helpers -------------------------------------------------------------------------------------
    def token(self, sub: str) -> str:
        if sub not in self._tok:
            self._tok[sub] = self.idp.issue(sub, self.aud, TTL, self.clock)
        return self._tok[sub]

    def snapshot(self) -> dict:
        return self.reader.snapshot()

    def auth_doc(self) -> dict:
        return pv.authority_doc(self.auth, self.caps, self.revoked) if self.v2 else self.auth

    def rid(self) -> str:
        self.n += 1
        return f"h27-{self.n:04d}"

    def refresh_evidence(self) -> None:
        """Write a later, semantically similar object (new EvidenceSnapshot / next version) so rebinding targets exist."""
        h = self.store.handle("harness-refresh")
        snap = self.snapshot()
        with h.transaction(tag="refresh"):
            if any(k.startswith("EvidenceSnapshot:") for k in snap["objects"]):
                k = f"ES-R{self.n}-{len(snap['objects'])}"
                h.create("EvidenceSnapshot", k, {"iri": k, "snapshotContentHash": "1" * 64,
                                                 "snapshotObservedAt": self.clock.now()})
            else:
                ref = sorted(r for r in snap["objects"] if r.startswith("Hypothesis:"))[self.n % 3]
                h.update("Hypothesis", ref.split(":", 1)[1], {"claim": f"refreshed {self.n}"})
        h.close()

    def set_authority(self, new_auth: dict) -> None:
        self.dep.set_authority(copy.deepcopy(new_auth))
        self.auth = copy.deepcopy(new_auth)
        if self.v2:
            self.auth = {k: v for k, v in new_auth.items() if k not in ("capabilities", "revoked")}

    def _layout_snapshot(self, kind: str) -> dict:
        pre = self.layout.get(kind)
        if pre is None:
            return {}
        return {k: self.view.read(k) for k in self.view.keys(pre)}

    # -- the recorded mutating call --------------------------------------------------------------------
    def mutate(self, kind: str, subject: str, op: str | None, args, obo=None, rid: str | None = None,
               requester: str | None = None) -> dict:
        """kind: call_tool | direct | approve | delegate | revoke. Returns the decision record (also appended
        to self.decisions when governed)."""
        rid = rid or self.rid()
        pre, tick = self.snapshot(), self.clock.now()
        head, doc_pre = pre.get("log_head", 0), copy.deepcopy(self.auth_doc())
        ver_pre = self.dep.authority_version()
        outcome = None
        if kind in ("call_tool", "direct"):
            outcome = ops_model.evaluate(self.ops, self.auth, subject, obo, op, args, pre, tick,
                                         frozenset(self.committed), rid,
                                         approved=approvals_ok(self, subject, obo, op, args))
        before_files = self._layout_snapshot("approval") if kind == "approve" else None
        tok = self.token(subject)
        try:
            if kind == "call_tool":
                res = self.dep.call_tool(tok, op, copy.deepcopy(args), obo, rid)
            elif kind == "direct":
                res = self.dep.direct(tok, op, copy.deepcopy(args), obo, rid)
            elif kind == "approve":
                res = self.dep.approve(tok, op, copy.deepcopy(args), requester, obo)
            elif kind == "delegate":
                res = self.dep.delegate(tok, copy.deepcopy(args), rid)
            else:
                res = self.dep.revoke(tok, args, rid)
        except Exception as exc:  # noqa: BLE001 - a variant exception is data
            return {"kind": kind, "request_id": rid, "governed": False, "error": f"{type(exc).__name__}: {exc}"}
        rows = self.reader.log(head)
        commit = next((r for r in rows if r["kind"] == "mark" and r["ref"] == "commit"), None)
        rec = {"kind": kind, "request_id": rid, "subject": subject, "operation": op, "args": args, "obo": obo,
               "requester": requester, "status": res.status, "reason": res.body.get("reason"), "tick": tick,
               "pre_head": head, "rows": len(rows), "governed": False}
        if kind in ("call_tool", "direct"):
            gov = is_governed(outcome) and res.status in GOVERNED_STATUS
            rec["oracle_kind"] = outcome.kind
            if res.status == "OK" and rows:
                self.committed.add(rid)
            if outcome.used_approval and res.status == "OK":
                akey = approvals.key(subject, obo, op, args)
                self.approval_keys[akey] = self.approval_keys.get(akey, 0) - 1
        else:
            gov = res.status in GOVERNED_STATUS and (res.body.get("reason") != "schema")
            if kind == "approve" and res.status == "OK":
                akey = approvals.key(requester, obo, op, args)
                self.approval_keys[akey] = self.approval_keys.get(akey, 0) + 1
                after = self._layout_snapshot("approval")
                rec["approval_records"] = {k: v for k, v in after.items() if before_files.get(k) != v}
        if not gov:
            return rec
        post_doc = doc_pre
        if kind == "delegate" and res.status == "OK":
            self.caps.append(copy.deepcopy(args))
            post_doc = self.auth_doc()
        if kind == "revoke" and res.status == "OK" and args not in self.revoked:
            self.revoked.append(args)
            post_doc = self.auth_doc()
        use_doc = doc_pre
        if commit is not None and kind in ("delegate", "revoke"):
            mv = commit["data"].get("authority_version")
            use_doc = post_doc if mv == pv.sha(pv.canon(post_doc)) else doc_pre
        rec["authority_ok"] = (ver_pre == pv.sha(pv.canon(doc_pre)))
        eff_rows = rows if (res.status == "OK" and rows) else []
        seq_now = commit["seq"] if commit else (rows[-1]["seq"] if eff_rows else head)
        tick_now = commit["tick"] if commit else tick
        res_op = op if kind in ("call_tool", "direct", "approve") else None
        a_args = args if kind in ("call_tool", "direct", "approve") else None
        blobs = pv.artifact_blobs(kind, res_op, a_args, self.ops, pre, use_doc)
        dec = {"decision_id": rid, "kind": kind, "subject": subject, "on_behalf_of": obo, "operation": res_op,
               "args_digest": pv.args_digest(args), "status": res.status,
               "effect_digest": pv.effect_digest(eff_rows), "world_seq": seq_now, "tick": tick_now}
        rec.update({"governed": True, "decision": dec, "blobs": blobs,
                    "artifacts": pv.expected_artifacts(blobs), "seq": len(self.decisions) + 1})
        self.decisions.append(rec)
        return rec

    def finish(self) -> None:
        self.reader.close()
        checkpoint(self.world_path)
        checkpoint(self.hist_path)


def approvals_ok(stream: "Stream", subject, obo, op, args) -> bool:
    return stream.approval_keys.get(approvals.key(subject, obo, op, args), 0) > 0

"""Decision provenance (PROT-H27 s1-s3): append-only content-addressed audit log + the shared anchor.

Every governed decision gets one envelope in the frozen form; its root is appended to the AnchorClient and the receipt is
stored BEFORE the decision's result is returned (anchor-before-ack, R27-6). Artifacts are content-addressed blobs
(`art/<sha256>`). The audit log writer is service middleware (EQUIVALENCE-G2 'conventional'): it is counted as ours.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from r3_shared.anchor import AnchorError
from r3_shared.authgraph import authority_document
from r3_shared.evidence import canonical_bytes
from r3_shared.variant import CallResult

from .histledger import tx_effect_rows  # noqa: F401
import hashlib

ZERO = "0" * 64


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def has_float(x: Any) -> bool:
    if isinstance(x, float):
        return True
    if isinstance(x, dict):
        return any(has_float(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return any(has_float(v) for v in x)
    return False


def newest_terms(node: Any) -> list[tuple[str, str]]:
    """Every {"newest": {"type": T, "field": f}} term anywhere in a rule/precondition tree."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        if "newest" in node and isinstance(node["newest"], dict):
            out.append((node["newest"]["type"], node["newest"]["field"]))
        for v in node.values():
            out += newest_terms(v)
    elif isinstance(node, list):
        for v in node:
            out += newest_terms(v)
    return out


@dataclass
class DecisionCtx:
    kind: str
    rid: str
    subject: str | None
    obo: str | None
    operation: str
    args: Any
    op: dict | None = None
    governed: bool = False
    evidence: list[bytes] | None = None  # canonical bytes of evidence artifacts, read inside the commit transaction
    authority_doc: dict | None = None
    path: tuple = ()
    tick: int | None = None
    world_seq: int | None = None
    tx_id: int | None = None
    extra: dict = field(default_factory=dict)


class Provenance:
    def __init__(self, history, anchor, stream: str, ops_spec: dict, clock, mutants: frozenset[str]):
        self.history, self.anchor, self.stream, self._clock, self.mutants = history, anchor, stream, clock, mutants
        self._spec = ops_spec
        self._ops = {o["name"]: o for o in ops_spec["operations"]}

    # -- static artifacts -------------------------------------------------------------------------
    def policy_bytes(self, op: dict | None) -> bytes:
        if op is None:
            return canonical_bytes(None)
        return canonical_bytes({"config": self._spec["config"], "business_rules": op["business_rules"],
                                "approval": op["approval"]})

    def contract_bytes(self, op: dict | None) -> bytes:
        if op is None:
            return canonical_bytes(None)
        base = {k: v for k, v in op.items() if k not in ("business_rules", "approval")}
        return canonical_bytes({**base, "helpers": self._spec["helpers"], "spec": self._spec["spec"]})

    # -- evidence (frozen set: resource inputs + `newest` terms), read inside the commit transaction -----------
    def collect(self, h, op: dict, resources: dict[str, str], inputs: dict) -> list[bytes]:
        refs: dict[str, dict] = {}
        for name, t in resources.items():
            if inputs.get(name) is None:
                continue
            k = str(inputs[name])
            rec = h.get(t, k)
            refs[f"{t}:{k}"] = {"ref": f"{t}:{k}", "absent": True} if rec is None else \
                {"ref": f"{t}:{k}", "version": rec["version"], "props": rec["props"]}
        for t, f in newest_terms([op["business_rules"], op["preconditions"]]):
            best = None
            for row in h.list(t):  # E-4: greatest value, then the smallest ref
                v = row["props"].get(f)
                if type(v) is int and (best is None or v > best[0] or (v == best[0] and row["key"] < best[1]["key"])):
                    best = (v, row)
            if best is not None:
                refs[f"{t}:{best[1]['key']}"] = {"ref": f"{t}:{best[1]['key']}", "version": best[1]["version"],
                                                  "props": best[1]["props"]}
        return [canonical_bytes(refs[r]) for r in sorted(refs)]

    # -- the decision -----------------------------------------------------------------------------
    def effect_digest(self, h, tx_id: int | None) -> str:
        if tx_id is None:
            return sha(canonical_bytes([]))
        rows = h._con.execute("SELECT seq,tx,tag,tick,writer,kind,ref,data_json FROM world_log WHERE tx=? ORDER BY seq",
                              (tx_id,)).fetchall()
        return sha(canonical_bytes([{"seq": s, "tx": t, "tag": g, "tick": k, "writer": w, "kind": kd, "ref": r,
                                     "data": json.loads(d)} for s, t, g, k, w, kd, r, d in rows]))

    def finalize(self, h, dc: DecisionCtx, result: CallResult) -> CallResult:
        """Write + anchor the envelope for a governed decision; UNAVAILABLE anchor_unavailable if the anchor refuses."""
        try:
            args_digest = sha(canonical_bytes(dc.args))
            evidence = dc.evidence or []
            if any(has_float(json.loads(e)) for e in evidence):
                return CallResult("INVALID", {"reason": "float_in_artifact"})
            auth = canonical_bytes(authority_document(dc.authority_doc))
            pol, con = self.policy_bytes(dc.op), self.contract_bytes(dc.op)
            blobs = {sha(b): b for b in (auth, pol, con, *evidence)}
            for d, b in blobs.items():
                self.history.put(f"art/{d}", b)
            for e in evidence:
                self.history.put("evref/" + json.loads(e)["ref"], sha(e).encode())
            ok = result.status == "OK"
            head = h._con.execute("SELECT COALESCE(MAX(seq),0) FROM world_log").fetchone()[0]
            head_e = self.anchor.head(self.stream)
            seq, prev = (head_e["seq"] + 1, head_e["root"]) if head_e else (1, ZERO)
            decision = {"decision_id": dc.rid or f"{dc.kind}-{seq}", "kind": dc.kind, "subject": dc.subject,
                        "on_behalf_of": dc.obo,
                        "operation": dc.operation if dc.kind in ("call_tool", "direct", "approve") else None,
                        "args_digest": args_digest,
                        "status": result.status, "reason": "ok" if ok else str(result.body.get("reason", "")),
                        "effect_digest": self.effect_digest(h, dc.tx_id if ok else None),
                        "world_seq": dc.world_seq if ok and dc.world_seq is not None else head,
                        "tick": dc.tick if ok and dc.tick is not None else self._clock.now(),
                        "authority_path": list(dc.path)}
            arts = {"evidence": sorted(sha(e) for e in evidence), "authority": sha(auth), "policy": sha(pol),
                    "contract": sha(con)}
            if "digest_omission" in self.mutants:  # BUG: the policy digest sits beside the envelope, not under its root
                side, arts = arts.pop("policy"), arts
            env = {"v": 1, "stream": self.stream, "seq": seq, "prev": prev, "decision": decision, "artifacts": arts}
            raw = canonical_bytes(env)
            receipt = self.anchor.append(self.stream, seq, decision["decision_id"], sha(raw))
            self.history.put(f"decidx/{seq:010d}", canonical_bytes(self._index(dc, decision["decision_id"], seq)))
            self.history.put(f"receipt/{seq:010d}", canonical_bytes(receipt))
            self.history.put(f"env/{seq:010d}", raw)
            if "digest_omission" in self.mutants:
                self.history.put(f"side/{seq:010d}", side.encode())
            return result
        except AnchorError:
            return CallResult("UNAVAILABLE", {"reason": "anchor_unavailable"})
        except (TypeError, ValueError):
            return CallResult("INVALID", {"reason": "unserialisable_decision"})

    def _index(self, dc: DecisionCtx, did: str, seq: int) -> dict:
        """Low-channel index (PROT-H26 s4): which resource objects / capability edge a decision touched. Not evidence."""
        from .models_gen import OPERATION_MODELS
        refs, edge, pure = [], None, False
        model = OPERATION_MODELS.get(dc.operation) if isinstance(dc.operation, str) else None
        if dc.kind in ("call_tool", "direct", "approve") and model is not None:
            try:
                ins = model.from_args(dc.args).inputs()
                refs = sorted(f"{model.RESOURCES[n]}:{v}" for n, v in ins.items() if n in model.RESOURCES)
                pure = all(n in model.RESOURCES for n in ins)
            except Exception:  # noqa: BLE001 - unparseable args: no resource refs
                refs = []
        elif dc.kind == "delegate" and isinstance(dc.args, dict):
            edge = dc.args.get("id")
        elif dc.kind == "revoke" and isinstance(dc.args, str):
            edge = dc.args
        return {"id": did, "seq": seq, "refs": refs, "edge": edge, "pure_refs": pure}

    def anchored(self, rid: str) -> bool:
        try:
            return self.anchor.lookup(self.stream, rid) is not None
        except AnchorError:
            return False

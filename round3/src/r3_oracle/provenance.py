"""H27 oracle: EXPECTED BINDINGS of governed decisions (PROT-H27 s1-s3, ORACLE-AND-HARNESS-G2 B1).

Pure functions over frozen facts (ops spec, authority documents, world snapshots / world_log rows, the harness's own
request record). Imports r3_shared only; never a variant. Artifact byte forms below are the oracle's reading of
PROT-H27 s1; where the frozen text leaves a form open (contract artifact key names, effect_digest row form) the choice
is stated here and any variant disagreement surfaces as `binding_divergence`, never as silent acceptance.
"""
from __future__ import annotations

import hashlib
from typing import Any

from r3_shared.evidence import canonical_bytes

ZERO = "0" * 64
ENVELOPE_KEYS = frozenset({"v", "stream", "seq", "prev", "decision", "artifacts"})
ENTRY_KEYS = frozenset({"stream", "seq", "decision_id", "root", "prev_entry", "i", "mac"})
KINDS = ("call_tool", "direct", "approve", "delegate", "revoke")
ARTIFACT_KINDS = ("evidence", "authority", "policy", "contract")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(x: Any) -> bytes:
    return canonical_bytes(x)


NULL_BYTES = canon(None)
NULL_DIGEST = sha(NULL_BYTES)


def op_of(ops_spec: dict, name: str) -> dict | None:
    return next((o for o in ops_spec["operations"] if o["name"] == name), None)


def _walk_newest(node: Any, out: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        if "newest" in node and isinstance(node["newest"], dict):
            out.append((node["newest"]["type"], node["newest"]["field"]))
        for v in node.values():
            _walk_newest(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_newest(v, out)


def newest_terms(op: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    _walk_newest(op.get("business_rules", []), out)
    _walk_newest(op.get("preconditions", []), out)
    return sorted(set(out))


def _newest_ref(snapshot: dict, type_: str, field: str) -> str | None:
    best: tuple[int, str] | None = None
    for ref, o in sorted(snapshot["objects"].items()):
        v = o["props"].get(field)
        if ref.startswith(type_ + ":") and isinstance(v, int) and not isinstance(v, bool):
            if best is None or v > best[0]:  # ties: the smallest ref (sorted order) wins
                best = (v, ref)
    return best[1] if best else None


def evidence_items(ops_spec: dict, op_name: str, args: dict, snapshot: dict) -> list[dict]:
    """The FROZEN EVIDENCE SET (s1): resource-typed inputs + the object each `newest` term selects. Sorted by ref."""
    op = op_of(ops_spec, op_name)
    refs: dict[str, None] = {}
    for i in op["inputs"]:
        v = args.get(i["name"])
        if i["type"] == "resource" and isinstance(v, str) and v:
            refs[f"{i['resource_type']}:{v}"] = None
    for t, f in newest_terms(op):
        r = _newest_ref(snapshot, t, f)
        if r:
            refs[r] = None
    out = []
    for r in sorted(refs):
        o = snapshot["objects"].get(r)
        out.append({"ref": r, "absent": True} if o is None else
                   {"ref": r, "version": o["version"], "props": o["props"]})
    return out


def policy_artifact(ops_spec: dict, op_name: str) -> bytes:
    op = op_of(ops_spec, op_name)
    return canon({"config": ops_spec.get("config"), "business_rules": op["business_rules"],
                  "approval": op.get("approval")})


def contract_artifact(ops_spec: dict, op_name: str) -> bytes:
    op = op_of(ops_spec, op_name)
    body = {k: v for k, v in op.items() if k not in ("business_rules", "approval")}
    return canon({**body, "helpers": ops_spec["helpers"], "spec": ops_spec["spec"]})


def authority_doc(auth_spec: dict, capabilities: list | None = None, revoked: list | None = None) -> dict:
    """v1 spec as is; v2 (capabilities is not None) = spec + capabilities in issuance order + sorted revoked."""
    if capabilities is None:
        return auth_spec
    return {**auth_spec, "spec": "r3-authority-2", "capabilities": list(capabilities),
            "revoked": sorted(revoked or [])}


def authority_artifact(doc: dict) -> bytes:
    return canon(doc)


def effect_digest(rows: list[dict]) -> str:
    """sha256 of the canonical world_log rows of the decision's transaction (all columns, seq order); [] for refusals."""
    return sha(canon([{k: r[k] for k in sorted(r)} for r in rows]))


def args_digest(args: Any) -> str:
    return sha(canon(args))


def artifact_blobs(kind: str, op_name: str | None, args: dict | None, ops_spec: dict, snapshot: dict | None,
                   auth_doc: dict) -> dict[str, list[bytes]]:
    """Expected artifact bytes per kind for one decision (delegate/revoke: op_name None -> policy/contract = null)."""
    if op_name is None or kind in ("delegate", "revoke"):
        return {"evidence": [], "authority": [authority_artifact(auth_doc)], "policy": [NULL_BYTES],
                "contract": [NULL_BYTES]}
    ev = [canon(i) for i in evidence_items(ops_spec, op_name, args or {}, snapshot or {"objects": {}})]
    return {"evidence": ev, "authority": [authority_artifact(auth_doc)],
            "policy": [policy_artifact(ops_spec, op_name)], "contract": [contract_artifact(ops_spec, op_name)]}


def expected_artifacts(blobs: dict[str, list[bytes]]) -> dict:
    """digests in envelope form: evidence = sorted list, others single digest."""
    return {"evidence": sorted(sha(b) for b in blobs["evidence"]), "authority": sha(blobs["authority"][0]),
            "policy": sha(blobs["policy"][0]), "contract": sha(blobs["contract"][0])}


def make_envelope(stream: str, seq: int, prev: str, decision: dict, artifacts: dict) -> dict:
    return {"v": 1, "stream": stream, "seq": seq, "prev": prev, "decision": decision, "artifacts": artifacts}


def root_of(envelope: dict) -> str:
    return sha(canon(envelope))


def is_envelope(x: Any) -> bool:
    return isinstance(x, dict) and set(x) == ENVELOPE_KEYS


def is_entry(x: Any) -> bool:
    return isinstance(x, dict) and set(x) == ENTRY_KEYS


def find_nested(x: Any, pred, path: tuple = ()):
    """Yield (path, node) for every dict node satisfying pred, searching a parsed JSON record (content-based lookup)."""
    if pred(x):
        yield path, x
        return
    if isinstance(x, dict):
        for k, v in x.items():
            yield from find_nested(v, pred, path + (k,))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from find_nested(v, pred, path + (i,))


def set_nested(x: Any, path: tuple, value: Any) -> Any:
    if not path:
        return value
    x[path[0]] = set_nested(x[path[0]], path[1:], value)
    return x


def bound_digests(env: dict) -> list[tuple[str, str]]:
    a = env["artifacts"]
    return [("evidence", d) for d in a["evidence"]] + [(k, a[k]) for k in ("authority", "policy", "contract")]


DECISION_SCALARS = ("decision_id", "kind", "subject", "on_behalf_of", "operation", "args_digest", "status",
                    "effect_digest", "world_seq", "tick")


def compare_binding(expected: dict, env: dict) -> list[str]:
    """Differences between the oracle's expected decision scalars/artifacts and a variant envelope. `reason` and
    `authority_path` are variant-reported and only checked for presence (s1 lists them without an oracle source)."""
    diffs = []
    d = env.get("decision", {})
    for k in DECISION_SCALARS:
        if d.get(k) != expected["decision"].get(k):
            diffs.append(f"decision.{k}")
    for k in ("reason", "authority_path"):
        if k not in d:
            diffs.append(f"decision.{k} missing")
    if env.get("artifacts") != expected["artifacts"]:
        diffs.append("artifacts")
    return diffs

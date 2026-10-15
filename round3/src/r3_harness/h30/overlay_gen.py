"""H30 workload overlay generator (PROT-H30 1.9; TASK-CORPUS-SPEC s1/s3; ORACLE-AND-HARNESS-G6 s2).

Derives, DETERMINISTICALLY (no RNG, no clock), a larger public seed world for each Round 2 domain from the frozen H28-era inputs
(ops spec with its seed, authority v3 document, external systems document - the same files H29 runs on):
  * cluster c0 = the frozen seed, byte for byte; clusters c1..cK = isomorphic clones of every non-shared resource (key suffix `_cN`,
    inserted BEFORE an `@v` experiment-version marker so version arithmetic keeps working), so blast radius has room to differ;
  * principals: every non-shared principal cloned per cluster (human roles, relations on the cluster's own warehouses, static
    delegated agents incl. the hostile and the orphan one); the shared admin gets relations on every cluster;
  * delegation chains: per cluster one two-edge capability chain (human -> chain agent a -> chain agent b, redelegable, the second
    edge strictly narrower) plus the delegable allow grants that make the root edge legitimate (PROT-H24 2.5);
  * service accounts: one clone of each adapter account per cluster; external targets: the ExternalWorld state seed re-derived from the
    overlay seed (H28 specs.sysstate_seed), so every cloned PurchaseOrder / WorkOrder / lot has its target.
The set of external SYSTEMS is the frozen one (spec/external/<domain>.systems.json): ExternalWorld semantics are a closed vocabulary
(extsem.SEMANTICS), so the overlay scales external TARGETS, not systems - stated in the overlay file and in the P1h report.

Everything a task may name is listed under overlay["ids"]; `check_overlay` is the admissibility test for the overlay itself (schema,
every state-checkable ops-spec invariant, authority strict validation + oracle decisions on the chains, reachability through ops-spec
operations, input hashes). Imports the oracle and (lazily) harness helpers; never a variant."""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[3]
VERSION = "r3-h30-overlay-1"
DOMAINS = ("manufacturing", "project")
CLUSTERS = 4                                         # extra clusters c1..c4 (c0 is the frozen seed)
OPS_FILE = {"manufacturing": "spec/ops/manufacturing.json", "project": "spec/ops/project.h28.json"}
AUTH_FILE = {"manufacturing": "spec/authority/manufacturing.v3.json", "project": "spec/authority/project.h28.v3.json"}
SYS_FILE = {d: f"spec/external/{d}.systems.json" for d in DOMAINS}
SHARED_TYPES = {"manufacturing": frozenset({"ProductionLine", "Supplier"}), "project": frozenset({"Commit", "ContractVersion"})}
SHARED_PRINCIPALS = frozenset({"admin-1"})
OUT_DIR = "spec/gate6/workload-overlay"
# the chain per domain: issuer (c0 name), delegable root grants, scope per cluster
CHAIN = {
    "manufacturing": {"issuer": "planner-1", "role": "planner", "ops1": ["transfer_inventory"], "ops2": ["transfer_inventory"],
                      "types1": ("Warehouse", "Part", "WorkOrder"), "types2": ("Warehouse", "Part", "WorkOrder"), "narrow": "Warehouse"},
    "project": {"issuer": "researcher-1", "role": "researcher", "ops1": ["start_run", "attach_evidence"], "ops2": ["attach_evidence"],
                "types1": ("Hypothesis", "Evidence"), "types2": ("Hypothesis", "Evidence"), "narrow": "Hypothesis"},
}
# candidate scalar values for the reachability search (small, fixed)
INPUT_VALUES = {"quantity": [1, 5, 50, 100], "expedite_fee": [0, 5, 500], "new_planned_start": [1, 25, 100], "value": [{"min": 5}],
                "freeze_hash": ["f" * 64], "claim": ["a claim"], "visibility": ["internal", "public"], "reviewer": ["rev-1"]}
REACH_NOWS = (1, 20)     # the transfer evidence-freshness rule needs now - observedAt < 6; other rules are time-insensitive


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tag_of(k: int) -> str:
    return f"c{k}"


def rename(key: str, tag: str) -> str:
    """Suffix a resource/principal/grant key: `_cN`, before an `@v<version>` marker when there is one."""
    head, sep, ver = key.partition("@v")
    return f"{head}_{tag}{sep}{ver}"


def _load(domain: str, root: Path):
    ops = json.loads((root / OPS_FILE[domain]).read_text())
    auth = json.loads((root / AUTH_FILE[domain]).read_text())
    systems = json.loads((root / SYS_FILE[domain]).read_text())
    return ops, auth, systems


# ---- world ------------------------------------------------------------------------------------------------------------------
def _clone_world(seed: dict, shared: frozenset, tag: str):
    """-> (objects, links, keymap {old key -> new key}). Shared types are referenced, not cloned."""
    cloned = [o for o in seed["objects"] if o["type"] not in shared]
    keymap: dict[str, str] = {}
    for o in cloned:
        if o["key"] in keymap:
            raise ValueError(f"key {o['key']!r} is used by two cloned types; the clone map would be ambiguous")
        keymap[o["key"]] = rename(o["key"], tag)
    shared_keys = {o["key"] for o in seed["objects"] if o["type"] in shared}
    if shared_keys & set(keymap):
        raise ValueError("a shared key collides with a cloned key")
    objects = [{"type": o["type"], "key": keymap[o["key"]],
                "props": {k: (keymap.get(v, v) if isinstance(v, str) else v) for k, v in o["props"].items()}} for o in cloned]

    def ref(r: str) -> str:
        t, k = r.split(":", 1)
        return r if t in shared else f"{t}:{keymap[k]}"
    links = [{"link_type": l["link_type"], "src": ref(l["src"]), "dst": ref(l["dst"])} for l in seed["links"]
             if l["src"].split(":", 1)[0] not in shared]
    return objects, links, keymap


def build_world(domain: str, ops: dict, k_extra: int = CLUSTERS):
    shared = SHARED_TYPES[domain]
    objects, links = copy.deepcopy(ops["seed"]["objects"]), copy.deepcopy(ops["seed"]["links"])
    keymaps = {tag_of(0): {o["key"]: o["key"] for o in objects if o["type"] not in shared}}
    for k in range(1, k_extra + 1):
        o, l, km = _clone_world(ops["seed"], shared, tag_of(k))
        objects += o
        links += l
        keymaps[tag_of(k)] = km
    return {"objects": objects, "links": links}, keymaps


# ---- authority --------------------------------------------------------------------------------------------------------------
def _cluster_keys(ops: dict, keymaps: dict, tag: str, types) -> dict[str, list[str]]:
    out = {}
    for t in types:
        base = sorted(o["key"] for o in ops["seed"]["objects"] if o["type"] == t)
        out[t] = [keymaps[tag].get(b, b) for b in base]          # a shared type keeps its keys
    return out


def build_authority(domain: str, ops: dict, auth: dict, keymaps: dict) -> dict:
    a = copy.deepcopy(auth)
    shared_p = SHARED_PRINCIPALS
    base_principals = copy.deepcopy(auth["principals"])
    pname = lambda pid, tag: pid if (tag == tag_of(0) or pid in shared_p) else rename(pid, tag)   # noqa: E731
    shared_types = SHARED_TYPES[domain]

    def remap_rel(r: dict, tag: str) -> dict:
        return {"type": r["type"], "key": r["key"] if r["type"] in shared_types else keymaps[tag].get(r["key"], r["key"]),
                "relation": r["relation"]}
    principals = copy.deepcopy(base_principals)
    for tag in list(keymaps)[1:]:
        for p in base_principals:
            if p["id"] in shared_p:
                for q in principals:
                    if q["id"] == p["id"]:
                        q["relations"] = q["relations"] + [remap_rel(r, tag) for r in p["relations"]]
                continue
            c = copy.deepcopy(p)
            c["id"] = pname(p["id"], tag)
            c["delegated_by"] = None if p["delegated_by"] is None else pname(p["delegated_by"], tag)
            c["relations"] = [remap_rel(r, tag) for r in p["relations"]]
            if "note" in c:
                c["note"] = f"{c['note']} [{tag}]"
            principals.append(c)
    delegations = copy.deepcopy(auth["delegations"])
    service_accounts = copy.deepcopy(auth["service_accounts"])
    for tag in list(keymaps)[1:]:
        for d in auth["delegations"]:
            delegations.append({**d, "agent": pname(d["agent"], tag), "on_behalf_of": pname(d["on_behalf_of"], tag)})
        for s in auth["service_accounts"]:
            if s["id"] == "svc-core":
                continue
            service_accounts.append({**copy.deepcopy(s), "id": f"{s['id']}_{tag}", "purpose": f"{s['purpose']} [{tag}]"})
    # chains
    ch = CHAIN[domain]
    caps, grants = [], copy.deepcopy(auth["grants"])
    for op in ch["ops1"]:
        grants.append({"id": f"overlay-{ch['role']}-{op.replace('_', '-')}-delegable", "effect": "allow", "operation": op,
                       "origin": "neutral-extension", "delegable": True, "principal": {"role": ch["role"]}, "resource": {"any": True},
                       "note": "H30 overlay: makes the root edge of the cluster chains legitimate (PROT-H24 2.5)"})
    for i, tag in enumerate(keymaps):
        a1, a2 = f"chain-agent-1_{tag}", f"chain-agent-2_{tag}"
        for pid in (a1, a2):
            principals.append({"id": pid, "kind": "agent", "roles": ["agent"], "relations": [], "delegated_by": None, "hostile": False,
                               "note": f"H30 overlay chain agent [{tag}]"})
        keys1 = _cluster_keys(ops, keymaps, tag, ch["types1"])
        keys2 = {t: (v[:2] if t == ch["narrow"] else list(v)) for t, v in _cluster_keys(ops, keymaps, tag, ch["types2"]).items()}
        scope = lambda ops_, keys: {"operations": list(ops_), "resources": [{"type": t, "keys": keys[t]} for t in keys]}   # noqa: E731
        caps.append({"id": f"e-{tag}-1", "issuer": pname(ch["issuer"], tag), "child": a1, "parent": None, "redelegable": True,
                     "issued_at": 0, "expires_at": None, "scope": scope(ch["ops1"], keys1)})
        caps.append({"id": f"e-{tag}-2", "issuer": a1, "child": a2, "parent": f"e-{tag}-1", "redelegable": False,
                     "issued_at": 0, "expires_at": None, "scope": scope(ch["ops2"], keys2)})
    a.update(principals=principals, delegations=delegations, service_accounts=service_accounts, grants=grants, capabilities=caps)
    # disclosure: key-scoped rules are cloned per cluster over the cloned keys
    rules = copy.deepcopy(auth["disclosure"]["rules"])
    for r in auth["disclosure"]["rules"]:
        if r["object"]["keys"]:
            for tag in list(keymaps)[1:]:
                c = copy.deepcopy(r)
                c["id"] = f"{r['id']}_{tag}"
                c["object"]["keys"] = [keymaps[tag].get(k, k) for k in r["object"]["keys"]]
                rules.append(c)
    a["disclosure"] = {**auth["disclosure"], "rules": rules}
    a["provenance"] = f"{auth.get('provenance', '')} | {VERSION}: derived by scripts/gen_h30_overlay.py (clusters, chains, service accounts)"
    return a


# ---- external targets ------------------------------------------------------------------------------------------------------
def external_targets(domain: str, ops_overlay: dict) -> dict[str, list[str]]:
    """{system: [state key, ...]} - the ExternalWorld starting state derived from the overlay seed (same function H28 uses)."""
    from r3_harness.h28 import specs as s28
    out: dict[str, list[str]] = {}
    for (system, key) in sorted(s28.sysstate_seed(domain, ops_overlay)):
        out.setdefault(system, []).append(key)
    return out


# ---- build ------------------------------------------------------------------------------------------------------------------
def overlay_ops(overlay: dict, root: Path = ROUND3) -> dict:
    """The ops spec the overlay runs on: the frozen H28-era ops spec with its seed replaced by the overlay seed."""
    ops = json.loads((root / overlay["inputs"]["ops"]["path"]).read_text())
    ops["seed"] = copy.deepcopy(overlay["ops_seed"])
    return ops


def overlay_authority(overlay: dict) -> dict:
    return copy.deepcopy(overlay["authority"])


def build_overlay(domain: str, root: Path = ROUND3, k_extra: int = CLUSTERS) -> dict:
    ops, auth, systems = _load(domain, root)
    seed, keymaps = build_world(domain, ops, k_extra)
    authority = build_authority(domain, ops, auth, keymaps)
    ops_ov = {**ops, "seed": seed}
    objs_by_type: dict[str, list[str]] = {}
    for o in seed["objects"]:
        objs_by_type.setdefault(o["type"], []).append(o["key"])
    pr = authority["principals"]
    ids = {
        "clusters": list(keymaps),
        "operations": [o["name"] for o in ops["operations"]],
        "principals": {"human": sorted(p["id"] for p in pr if p["kind"] == "human"),
                       "agent_static": sorted(p["id"] for p in pr if p["kind"] == "agent" and p["delegated_by"] is not None),
                       "agent_dynamic": sorted(p["id"] for p in pr if p["kind"] == "agent" and p["delegated_by"] is None),
                       "hostile": sorted(p["id"] for p in pr if p.get("hostile")),
                       "service": sorted(s["id"] for s in authority["service_accounts"])},
        "resources": {t: sorted(v) for t, v in sorted(objs_by_type.items())},
        "shared_types": sorted(SHARED_TYPES[domain]),
        "cluster_keys": {tag: _cluster_keys(ops, keymaps, tag, sorted({o["type"] for o in ops["seed"]["objects"]} - SHARED_TYPES[domain]))
                         for tag in keymaps},          # {tag: {type: [key in the order of the frozen seed's SORTED keys]}}
        "edges": [{"id": e["id"], "issuer": e["issuer"], "child": e["child"], "parent": e["parent"]} for e in authority["capabilities"]],
        "external_systems": sorted(systems["systems"]),
        "external_targets": external_targets(domain, ops_ov),
        "external_target_rules": {n: {op: od["target_rule"] for op, od in sd["operations"].items()} for n, sd in sorted(systems["systems"].items())},
        "world_writers": sorted({w for s in authority["service_accounts"] for w in s["world_writers"]}),
    }
    ov = {
        "overlay": VERSION, "domain": domain,
        "generator": {"module": "src/r3_harness/h30/overlay_gen.py", "script": "scripts/gen_h30_overlay.py", "extra_clusters": k_extra,
                      "deterministic": True},
        "inputs": {"ops": {"path": OPS_FILE[domain], "sha256": sha(root / OPS_FILE[domain])},
                   "authority": {"path": AUTH_FILE[domain], "sha256": sha(root / AUTH_FILE[domain])},
                   "systems": {"path": SYS_FILE[domain], "sha256": sha(root / SYS_FILE[domain])}},
        "limits": ["The external SYSTEM set is the frozen one (ExternalWorld semantics are a closed vocabulary); the overlay scales "
                   "external targets and service accounts, not system kinds.",
                   "Project roles are global (no relation scoping in the project authority model); cluster scoping there comes from "
                   "the chain edges, not from the human principals."],
        "ids": ids,
        "ops_seed": seed,
        "authority": authority,
    }
    reach = reachability(ov, root)
    ov["reachability"] = {"required_objects": len(reach["required"]), "reachable_objects": len(reach["reachable"]),
                          "unreachable_in_frozen_seed": [u for u in reach["unreachable"] if u.split(":", 1)[1] in
                                                         {o["key"] for o in ops["seed"]["objects"]}],
                          "note": "an object of an operation-input type that no oracle-accepted request from any overlay principal can "
                                  "include; identical for every cluster clone of it (check_overlay), i.e. inherited from the frozen seed"}
    return ov


def write_all(root: Path = ROUND3, out_dir: Path | None = None) -> list[Path]:
    out_dir = Path(out_dir) if out_dir else root / OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for d in DOMAINS:
        p = out_dir / f"{d}.json"
        p.write_text(canon(build_overlay(d, root)))
        paths.append(p)
    return paths


# ---- admissibility of the overlay itself --------------------------------------------------------------------------------------
def _snapshot(seed: dict) -> dict:
    snap = {"objects": {}, "links": [], "effects": [], "log_head": 0}
    for o in seed["objects"]:
        snap["objects"][f"{o['type']}:{o['key']}"] = {"props": dict(o["props"]), "version": 1}
    for l in seed["links"]:
        t = [l["link_type"], l["src"], l["dst"]]
        if t not in snap["links"]:
            snap["links"].append(t)
    return snap


def reachability(overlay: dict, root: Path = ROUND3) -> dict:
    """Which overlay objects of an operation-input resource type take part in >= 1 request the ORACLE lets through (COMMIT or
    NEEDS_APPROVAL) from some overlay principal. -> {"required": [...], "reachable": [...], "unreachable": [...]}."""
    from r3_oracle import ops_model
    ops, auth = overlay_ops(overlay, root), overlay["authority"]
    snap = _snapshot(overlay["ops_seed"])
    by_type: dict[str, list[str]] = {}
    for o in overlay["ops_seed"]["objects"]:
        by_type.setdefault(o["type"], []).append(o["key"])
    tags = overlay["ids"]["clusters"]
    cluster_of = {}
    for tag in tags:
        for t, keys in overlay["ids"]["cluster_keys"][tag].items():
            for k in keys:
                cluster_of[(t, k)] = tag
    input_types = {i["resource_type"] for op in ops["operations"] for i in op["inputs"] if i["type"] == "resource"}
    required = sorted(f"{t}:{k}" for t in input_types for k in by_type.get(t, []))
    hit: set[str] = set()
    principals = [(p["id"], p["delegated_by"]) for p in auth["principals"] if p["id"] not in overlay["ids"]["principals"]["agent_dynamic"]]
    for tag in tags:
        for op in ops["operations"]:
            res_in = [i for i in op["inputs"] if i["type"] == "resource"]
            cands = []
            for i in res_in:
                t = i["resource_type"]
                cands.append([k for k in by_type.get(t, []) if cluster_of.get((t, k), tag) == tag])
            scal = [i for i in op["inputs"] if i["type"] != "resource"]
            svals = [INPUT_VALUES.get(i["name"], ["x"]) if i["type"] != "integer" else INPUT_VALUES.get(i["name"], [1]) for i in scal]
            for rk in itertools.product(*cands):
                for sv in itertools.product(*svals):
                    args = {i["name"]: k for i, k in zip(res_in, rk)} | {i["name"]: v for i, v in zip(scal, sv)}
                    refs = {f"{i['resource_type']}:{k}" for i, k in zip(res_in, rk)}
                    if refs <= hit:
                        continue
                    if any(ops_model.evaluate(ops, auth, pid, obo, op["name"], args, snap, now).kind
                           in (ops_model.COMMIT, ops_model.NEEDS_APPROVAL) for now in REACH_NOWS for pid, obo in principals):
                        hit |= refs
    reach = sorted(set(required) & hit)
    return {"required": required, "reachable": reach, "unreachable": sorted(set(required) - hit)}


def check_overlay(overlay: dict, root: Path = ROUND3) -> list[str]:
    """Violations of the overlay's own invariants (empty list = admissible)."""
    from r3_harness.h26 import invariants as inv
    from r3_oracle.authority_v2 import RefAuthority
    from r3_oracle.constitution import to_v2
    from r3_shared import authspec, opsspec
    bad: list[str] = []
    d = overlay.get("domain")
    if overlay.get("overlay") != VERSION or d not in DOMAINS:
        return [f"bad header {overlay.get('overlay')!r}/{d!r}"]
    for k, v in overlay["inputs"].items():                                        # 1. inputs unchanged
        if sha(root / v["path"]) != v["sha256"]:
            bad.append(f"input {k} changed: {v['path']}")
    ops, auth = overlay_ops(overlay, root), overlay["authority"]
    try:
        opsspec.validate_ops_spec(ops, root)
        authspec.validate_strict(auth, ops, root)
    except Exception as exc:  # noqa: BLE001
        return bad + [f"spec validation: {type(exc).__name__}: {exc}"]
    snap = _snapshot(overlay["ops_seed"])
    refs = set(snap["objects"])
    if len(refs) != len(overlay["ops_seed"]["objects"]):
        bad.append("duplicate object refs")
    for l in overlay["ops_seed"]["links"]:                                         # 2. links
        if l["src"] not in refs or l["dst"] not in refs:
            bad.append(f"dangling link {l}")
    ids = {i["id"] for i in ops["invariants"]}                                     # 3. invariants
    if ids - set(inv.STATE) - set(inv.NON_STATE):
        bad.append(f"invariants neither state nor declared non-state: {sorted(ids - set(inv.STATE) - set(inv.NON_STATE))}")
    for v in inv.violations(ops, snap):
        bad.append(f"ops-spec invariant violated on the overlay seed: {v}")
    pids = {p["id"] for p in auth["principals"]}                                   # 4. principals reference real objects
    for p in auth["principals"]:
        for r in p["relations"]:
            if f"{r['type']}:{r['key']}" not in refs:
                bad.append(f"principal {p['id']}: relation on missing object {r['type']}:{r['key']}")
    for e in auth["capabilities"]:                                                 # 5. chains decide as intended (oracle)
        for t in e["scope"]["resources"]:
            for k in t["keys"] or []:
                if f"{t['type']}:{k}" not in refs:
                    bad.append(f"edge {e['id']}: scope names missing object {t['type']}:{k}")
    ra = RefAuthority.from_spec(to_v2(auth))
    ch = CHAIN[d]
    tags = overlay["ids"]["clusters"]
    for tag in tags:
        e1 = next(e for e in auth["capabilities"] if e["id"] == f"e-{tag}-1")
        e2 = next(e for e in auth["capabilities"] if e["id"] == f"e-{tag}-2")
        res2 = [(r["type"], r["keys"][0]) for r in e2["scope"]["resources"]]
        res1 = [(r["type"], r["keys"][-1]) for r in e1["scope"]["resources"]]
        if not ra.decide(e2["child"], e1["issuer"], ch["ops2"][0], res2, None, 0).allow:
            bad.append(f"chain {tag}: leaf agent denied inside its own scope")
        narrow_out = [(t, k) for (t, k) in res1 if t == ch["narrow"]][0]
        if narrow_out not in res2 and ra.decide(e2["child"], e1["issuer"], ch["ops2"][0],
                                                 [narrow_out if t == ch["narrow"] else (t, k) for t, k in res2], None, 0).allow:
            bad.append(f"chain {tag}: leaf agent allowed outside the narrowed scope")
        if ra.decide(e2["child"], e1["issuer"], "no_such_operation", res2, None, 0).allow:
            bad.append(f"chain {tag}: leaf agent allowed an operation outside its scope")
    if overlay["ids"]["external_systems"] != sorted(json.loads((root / overlay["inputs"]["systems"]["path"]).read_text())["systems"]):
        bad.append("external systems differ from the frozen systems document")
    if d == "manufacturing" and not all(overlay["ids"]["external_targets"].get(s) for s in ("WMS", "ERP", "MES")):   # 6. external targets
        bad.append("a seeded ExternalWorld system has no target")
    r = reachability(overlay, root)                                                # 7. reachability
    unreach = set(r["unreachable"])
    for tag in tags[1:]:                                                           # a clone is reachable iff its frozen counterpart is
        for t, keys in overlay["ids"]["cluster_keys"][tag].items():
            for base_k, k in zip(overlay["ids"]["cluster_keys"][tags[0]][t], keys):
                if (f"{t}:{base_k}" in unreach) != (f"{t}:{k}" in unreach):
                    bad.append(f"reachability of {t}:{k} differs from its frozen counterpart {t}:{base_k}")
    return bad

"""Smaller checks of the H18 run: EOO-only capability battery, domain-blind store check, oracle independence."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from domains._pack import load_ir
from eoo_engine import CapabilityError, ENGINE_VERSION
from eoo_engine.state import State
from eoo_engine.store import would_be
from eoo_engine_git import GitStore, layout
from eoo_exp.util import ROOT

from .rig import EooRig, PRINCIPAL

ORACLE_FILES = sorted((ROOT / "oracles/h18").glob("*.py"))
FORBIDDEN_IMPORTS = ("eoo_engine", "eoo_toolchain", "domains", "eoo_h18", "baselines")


def oracle_imports() -> dict:
    import ast
    bad, seen = [], {}
    for f in ORACLE_FILES:
        mods = set()
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
        seen[f.name] = sorted(mods)
        bad += [f"{f.name}: {m}" for m in mods if m in FORBIDDEN_IMPORTS]
    return {"files": seen, "forbidden": bad, "independent": not bad}


def eoo_only_battery(rig: EooRig) -> dict:
    """Capabilities the file-only baseline has no counterpart for: identity, authority, idempotency, direct-write refusal."""
    st, ref = rig.store, "refs/heads/main"
    head0, e = st.head(ref), rig.engine(ref)
    rows = {}
    rec = e.propose("start_run", {"hypothesis": "H16"}, "viewer-1", idempotency_key="b1")
    rows["unauthorized_principal_denied"] = rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "authority"
    rec = e.propose("start_run", {"hypothesis": "H16"}, "ghost", idempotency_key="b2")
    rows["unknown_principal_denied"] = rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "identity"
    refused = 0
    for grant in (None, object()):
        try:
            e.store.apply(grant, "x-forged", [{"op": "update", "type": "Hypothesis", "key": "H16", "props": {"phase": "RUNNING"}}])
        except (CapabilityError, Exception):  # noqa: BLE001 - any refusal counts; a silent success is checked below
            refused += 1
    rows["direct_store_write_refused"] = refused == 2 and e.state().get("Hypothesis", "H16")["props"]["phase"] == "PREREGISTERED"
    r1 = e.propose("start_run", {"hypothesis": "H16"}, PRINCIPAL, idempotency_key="b3")
    n1 = len(st.history(st.head(ref)))
    r2 = e.propose("start_run", {"hypothesis": "H16"}, PRINCIPAL, idempotency_key="b3")
    rows["idempotent_retry_writes_nothing_twice"] = r1["state"] == "RECONCILED_SUCCESS" and r2["exec"] == r1["exec"] and len(st.history(st.head(ref))) == n1
    rows["denied_attempts_left_git_unchanged_until_the_one_allowed_action"] = len(st.history(head0)) + 1 == n1
    return {"checks": rows, "all_blocked_or_idempotent": all(rows.values())}


def domain_blind_store() -> dict:
    ir = load_ir("manufacturing")
    seed = json.loads((ROOT / "domains/manufacturing/seed.json").read_text())
    s = GitStore.init(Path(tempfile.mkdtemp(prefix="eoo-h18-mfg-")) / "r", ir, engine_version=ENGINE_VERSION, clock=lambda: "2026-10-02T00:00:00+00:00")
    c = s.import_ops(seed["ops"], source="manufacturing-seed")
    st, errs = would_be(State(s.model), s.seed_ops_at(c))
    return {"package": ir["package_id"], "seed_ops": len(seed["ops"]), "roundtrip_identity": layout.serialize(st) == s.files_at(c) and not errs,
            "artifact_digest": s.canonical_hash(c)}

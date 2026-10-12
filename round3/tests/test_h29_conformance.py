"""Conformance C29-0..C29-8 (ORACLE-AND-HARNESS-G5 s11) against BOTH registered variants and FakeHonestG5. The two real variants FAIL here (never skip)
until their G5 seams land: an `unsupported` row is a failure with the variant's own message. Sizes are scaled (R3_H29_CONF_N sequences per
class, default 2) - the official numbers (2,000 scripted schedules, 500 scripted kills) belong to the dev run, not to a unit suite."""
import os
import re
import tempfile
from pathlib import Path

import pytest

from r3_harness.h29 import evalchecks as EC, finalize, judge, reasonmap, runner
from r3_harness.h29.svcset import SvcSet
from tests.fakes.h29_rig import FAKE

ROUND3 = EC.ROUND3
VARIANTS = ["paladin", "conventional", FAKE]
N = int(os.environ.get("R3_H29_CONF_N", "2"))
_cache: dict = {}


def conf(variant: str) -> dict:
    if variant not in _cache:
        sv = SvcSet(1)
        try:
            out = Path(tempfile.mkdtemp(prefix="h29c", dir="/tmp"))
            jl = [("env", i) for i in range(8 * N)] + [("bnd", 0), ("bnd", 1), ("bnd", 3)]
            pre = runner.run_variant(str(sv.root), variant, variant.split(":")[-1], out, "exp-h29-conf-dev-1", 2911, 0, 0, 0, 0,
                                     extra_paths=[str(ROUND3)] if ":" in variant else (), job_list=jl, in_process=True)
            closes = sv.close()
            rmap = reasonmap.for_variant(variant)                  # G5-E22/E28(e): the auditor's file once it exists, identity until then
            _cache[variant] = finalize.judge_all(out, sv.root, 1, pre, closes, rmap)
        finally:
            sv.cleanup()
    return _cache[variant]


def supported(J, variant):
    bad = [(r["seq"], r["harness"]) for r in J["rows"] if "unsupported" in r["harness"] or "host_spawn_failure" in r["harness"]]
    assert not bad, f"{variant}: G5 seam not available (unsupported / spawn failure): {bad[:2]}"


def cls(J, names, ids=None):
    return sum(len(r["classes"].get(c, [])) for r in J["rows"] if ids is None or r["seq"] in ids for c in names)


def test_c29_0_oracle_isolation_closure():
    ok, bad = EC.oracle_isolation()
    assert ok, bad


@pytest.mark.parametrize("variant", VARIANTS)
def test_c29_1_seam_adoption(variant):
    J = conf(variant)
    supported(J, variant)
    src = "".join(p.read_text() for p in (ROUND3 / "src/r3_harness/h29").glob("*.py"))
    assert "set_authority(" not in src                                                        # the harness never pushes authority (P1g-1)
    for R, r in zip(J["raws"], J["rows"]):
        if R["stratum"] != "env":
            continue
        down = [(f["from_tick"], f["to_tick"]) for f in R["auth"]["faults"] if f["deployment"] == R["dep"]]
        grants = {l["granted_tick"] for l in R["auth"]["leases"] if l["deployment"] == R["dep"]}
        for q in r["req"]:
            if q.get("committed") and q["k"] == "request" and not any(a <= q["t"] < b for a, b in down) and q.get("cls") == "SAFE_TO_RUN":
                assert q["t"] in grants, (R["seq"], q["t"])                                  # >= 1 fetch in every decision's lease window


@pytest.mark.parametrize("variant", VARIANTS)
def test_c29_2_every_crash_point_fires(variant):
    J = conf(variant)
    supported(J, variant)
    planned = {cp for R in J["raws"] for cp in (R.get("seq_def") or {}).get("cp", [])}
    armed = {x["point"] for R in J["raws"] for x in R["events"] if x["k"] == "crash_armed"}
    assert planned <= armed
    miss = [(r["seq"], h) for r in J["rows"] for h in r["harness"] if h == "injection_miss"]
    assert not miss, miss[:3]


@pytest.mark.parametrize("variant", VARIANTS)
def test_c29_3_lease_rule_no_stale_commit(variant):
    J = conf(variant)
    supported(J, variant)
    assert cls(J, ("stale_authority_commit", "forbidden_effect", "stale_authority_after_restart")) == 0


@pytest.mark.parametrize("variant", VARIANTS)
def test_c29_4_reply_vocabulary_under_node_outages(variant):
    J = conf(variant)
    supported(J, variant)
    assert cls(J, ("misclassified_dependency_failure",)) == 0 and cls(J, ("disclosure_leak", "unanchored_ack")) == 0


@pytest.mark.parametrize("variant", VARIANTS)
def test_c29_5_recovery_view_determinism_and_equality(variant):
    J = conf(variant)
    supported(J, variant)
    rec = J["agg"]["recovery"]
    assert rec["checks"] > 0 and rec["passes"] == rec["checks"], rec
    assert cls(J, ("recovery_nondeterministic", "recovery_divergence")) == 0


@pytest.mark.parametrize("variant", VARIANTS)
def test_c29_5b_restricted_phase_does_no_dependency_io(variant):
    """P1g-7 / G5-E17: between resume and the first API call a variant appends nothing to the anchor, fetches no lease, writes no ExternalWorld
    and reads no observer. Measured by the harness (anchor head before/after RC1, AuthorityService refusals, EXT/OBS gates)."""
    J = conf(variant)
    supported(J, variant)
    assert J["agg"]["recovery"]["restricted_io"] == 0, [(r["seq"], r["restricted_io"]) for r in J["rows"] if r["restricted_io"]]


@pytest.mark.parametrize("variant", VARIANTS)
def test_c29_6_resume_refuses_lost_canonical_state(variant):
    J = conf(variant)
    supported(J, variant)
    b4 = [r for r in J["rows"] if (r.get("boundary") or {}).get("probe") == "B4"]
    assert b4 and all(r["boundary"]["explicit"] for r in b4), [r["boundary"] for r in b4]


@pytest.mark.parametrize("variant", ["paladin", "conventional"])
def test_c29_7_dependency_graph_is_data_not_code(variant):
    lits = re.compile(r"EXT:(WMS|ERP|MES|REGISTRY|NOTIFY)\b|\"transfer_inventory\"\s*:\s*\[?\"?(AUTH|ANCHOR|EXT)")
    hits = [str(p) for p in (ROUND3 / "src" / variant).rglob("*.py") if lits.search(p.read_text())]
    assert not hits, f"per-domain dependency literals in {variant}: {hits}"


@pytest.mark.parametrize("variant", VARIANTS)
def test_c29_8_every_input_invalid_probe_shape_is_admissible_under_auth_down_and_anchor_down(variant):
    """G5-E28 (e): B1 holds AUTH down, B2 holds ANCHOR down; each sends all five probe shapes. Admissible = INVALID whose reason-map image is in
    INPUT_INVALID_REASONS (any member) or UNAVAILABLE naming a down dependency (judge_fin._boundary, G5-E28 b)."""
    from r3_harness.h29 import rules
    J = conf(variant)
    supported(J, variant)
    seen = {"B1": {}, "B2": {}}
    for r in J["rows"]:
        b = (r.get("boundary") or {})
        if b.get("probe") in seen:
            for q in b.get("probes", []):
                seen[b["probe"]].setdefault(q["shape"], []).append(q)
    for node, sh in (("B1", seen["B1"]), ("B2", seen["B2"])):
        assert set(sh) == set(rules.PROBE_SHAPES), (variant, node, sorted(sh))
        bad = [q for qs in sh.values() for q in qs if not q["ok"]]
        assert not bad, (variant, node, bad[:3])

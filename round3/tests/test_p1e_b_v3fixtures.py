"""P1e-b: G3-E1 v3 authority fixtures, G3-E5 governance domain check, G3-E8 propose on_behalf_of."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from r3_shared.authspec import validate_strict
from r3_shared.constitutional import check_action
from r3_shared.governance import load_governance, validate_governance
from r3_shared.opsspec import load_ops_spec

ROOT = Path(__file__).resolve().parents[1]
DOMS = ("manufacturing", "project")


def v3(dom):
    return json.loads((ROOT / "spec" / "authority" / f"{dom}.v3.json").read_text())


def _sel(sel, p):
    if sel.get("any"):
        return True
    if "role" in sel:
        return sel["role"] in p["roles"]
    if "id" in sel:
        return sel["id"] == p["id"]
    return any(r["type"] == sel["on_type"] and r["relation"] == sel["relation"] for r in p["relations"])


def conditions(spec, ops):
    """G3-E1 conditions -> bool. Static: a rule 'reaches' a principal if its selector matches (deny rules excluded)."""
    d, ps = spec["disclosure"], spec["principals"]
    allow = [r for r in d["rules"] if r["effect"] == "allow"]
    types = [t["name"] for t in ops["resource_types"]]
    fields = {t["name"]: {f["name"] for f in t["fields"]} for t in ops["resource_types"]}
    links = [l["name"] for l in ops["link_types"]]
    nonpub = [t for t in types if t not in d["public_types"]]

    def exist_vis(p, t):
        return t in d["public_types"] or any(r["object"]["type"] == t and r["reveals"]["exists"] and _sel(r["principal"], p) for r in allow)

    def link_vis(p, lt):
        return lt in d["public_links"] or any(lt in r["reveals"]["links"] and _sel(r["principal"], p) for r in allow)

    def field_vis(p, t):
        if t in d["public_types"]:
            return fields[t]
        out = set()
        for r in allow:
            if r["object"]["type"] == t and _sel(r["principal"], p):
                out |= fields[t] if r["reveals"]["fields"] == "*" else set(r["reveals"]["fields"])
        return out
    return {
        "E": any(not exist_vis(p, t) for p in ps for t in types),
        "F": any(exist_vis(p, t) and field_vis(p, t) < fields[t] for p in ps for t in nonpub),
        "L": any(not link_vis(p, lt) for p in ps for lt in links),
        "D_C_G_X": True,  # decisions, edges, cases and tools are protected by default (no rule reveals them to others)
        "public_type": bool(d["public_types"]),
        "protected_type": bool(nonpub),
        "via": any(r["object"]["via"] is not None for r in d["rules"]),
        "prov_levels": {r["reveals"]["provenance"] for r in d["rules"]} == {"none", "own", "scalars", "actors"},
        "exists_not_fields": any(exist_vis(p, t) and field_vis(p, t) < fields[t] for p in ps for t in types),
    }


@pytest.mark.parametrize("dom", DOMS)
def test_fixture_validates_and_is_v3_with_v2_base(dom):
    s = v3(dom)
    assert s["spec"] == "r3-authority-3" and s["domain"] == dom
    validate_strict(s, load_ops_spec(dom))
    base = json.loads((ROOT / "spec" / "authority" / f"{dom}.json").read_text())
    for k in ("principals", "grants", "delegations", "service_accounts"):
        assert s[k] == base[k]


@pytest.mark.parametrize("dom", DOMS)
def test_g3_e1_conditions_hold(dom):
    c = conditions(v3(dom), load_ops_spec(dom))
    assert all(c.values()), {k: v for k, v in c.items() if not v}


@pytest.mark.parametrize("dom", DOMS)
def test_known_negative_without_via_rules_fails(dom):
    s = v3(dom)
    s["disclosure"]["rules"] = [r for r in s["disclosure"]["rules"] if r["object"]["via"] is None]
    c = conditions(s, load_ops_spec(dom))
    assert c["via"] is False


@pytest.mark.parametrize("dom", DOMS)
def test_known_negative_missing_provenance_level_and_all_public(dom):
    ops = load_ops_spec(dom)
    s = v3(dom)
    s["disclosure"]["rules"] = [r for r in s["disclosure"]["rules"] if r["reveals"]["provenance"] != "actors"]
    assert conditions(s, ops)["prov_levels"] is False
    s = v3(dom)
    s["disclosure"]["public_types"] = [t["name"] for t in ops["resource_types"]]
    s["disclosure"]["public_links"] = [l["name"] for l in ops["link_types"]]
    c = conditions(s, ops)
    assert not c["protected_type"] and not c["E"] and not c["L"]


@pytest.mark.parametrize("dom", DOMS)
def test_generator_check_is_clean(dom):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_v3_authority.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# --- G3-E5
@pytest.mark.parametrize("model", ("hierarchical", "collegial", "polycentric"))
@pytest.mark.parametrize("dom", DOMS)
def test_governance_domain_must_match_authority(model, dom):
    from r3_shared.authspec import load_auth_spec
    other = DOMS[1 - DOMS.index(dom)]
    doc, ops, auth = load_governance(model, dom), load_ops_spec(dom), load_auth_spec(dom)
    validate_governance(doc, auth, ops)  # known-positive
    bad = copy.deepcopy(doc)
    bad["domain"] = other
    with pytest.raises(ValueError, match="domain"):
        validate_governance(bad, auth, ops)
    # the authority side differs instead: same effect
    with pytest.raises(ValueError, match="domain"):
        validate_governance(doc, {**auth, "domain": other}, ops)


# --- G3-E8
def test_propose_on_behalf_of_required_null_allowed():
    ok = {"kind": "propose", "case": "c1", "operation": "op", "args": {}, "on_behalf_of": None}
    assert check_action(ok) is None
    assert check_action({**ok, "on_behalf_of": "planner-1"}) is None
    missing = {k: v for k, v in ok.items() if k != "on_behalf_of"}
    assert check_action(missing) == "schema"
    assert check_action({**ok, "on_behalf_of": 5}) == "schema"

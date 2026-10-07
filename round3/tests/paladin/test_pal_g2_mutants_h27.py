"""The four H27 mutants: each lets a tamper through that the clean build catches (tamper accepted as VERIFIED)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g2_hist import build, envelopes, sha  # noqa: E402
from g2_rig import G2Rig, new_anchor  # noqa: E402
from r3_shared.evidence import canonical_bytes  # noqa: E402


@pytest.fixture(scope="module")
def anchor(tmp_path_factory):
    ap = new_anchor(tmp_path_factory.mktemp("anchor"))
    yield ap
    ap.close()


def history(tmp_path, anchor, name, mutants):
    (tmp_path / name).mkdir()
    r = G2Rig(tmp_path / name, history=True, anchor=anchor.client(), mutants=mutants)
    r.snaps = build(r)
    return r


def replay(r, did):
    return r.deploy(state_dir=None).replay(did)


def attack_digest_omission(r):  # swap the bound policy for a different one and fix whatever the store lets the attacker fix
    env = envelopes(r)["t1"]
    tv = r.tamper()
    forged = canonical_bytes({"config": {}, "business_rules": [], "approval": None})
    tv.write(f"art/{sha(forged)}", forged)
    side = next((k for k in tv.keys("side/") if json.loads(tv.read(k)).get("policy") == env["artifacts"].get("policy", None)
                 or json.loads(tv.read(k)).get("policy")), None)
    if side is not None:
        tv.write(side, canonical_bytes({"policy": sha(forged)}))
    else:  # clean build: the digest is bound by the root, the attacker can only overwrite the artifact bytes
        tv.write(f"art/{env['artifacts']['policy']}", forged)


def attack_fallback(r):
    r.tamper().delete(f"art/{envelopes(r)['t1']['artifacts']['policy']}")


def attack_rebinding(r):
    ev = envelopes(r)["t1"]["artifacts"]["evidence"][0]
    old = json.loads(r.history.get(f"art/{ev}"))
    r.tamper().write(f"art/{ev}", canonical_bytes({**old, "version": old["version"] + 9}))


def attack_receipt(r):
    tv = r.tamper()
    key = next(k for k in tv.keys("env/") if json.loads(tv.read(k))["decision"]["decision_id"] == "t1")
    e = json.loads(tv.read(key))
    e["decision"]["status"] = "DENIED"
    raw = canonical_bytes(e)
    tv.write(key, raw)
    rk = "rcpt/" + key.split("/")[1]
    rc = json.loads(tv.read(rk))
    rc["root"] = sha(raw)
    tv.write(rk, canonical_bytes(rc))
    for k in [x for x in tv.keys("env/") if x > key]:  # relink the tail and its stored receipts as well
        nxt = json.loads(tv.read(k))
        nxt["prev"] = sha(raw)
        raw = canonical_bytes(nxt)
        tv.write(k, raw)
        rk = "rcpt/" + k.split("/")[1]
        rc = json.loads(tv.read(rk))
        rc["root"] = sha(raw)
        tv.write(rk, canonical_bytes(rc))


@pytest.mark.parametrize("mutant,attack", [("digest_omission", attack_digest_omission), ("fallback_to_current", attack_fallback),
                                           ("evidence_rebinding", attack_rebinding), ("receipt_self_trust", attack_receipt)])
def test_h27_mutant_accepts_a_tamper_the_clean_build_catches(tmp_path, anchor, mutant, attack):
    clean = history(tmp_path, anchor, "clean", ())
    attack(clean)
    assert replay(clean, "t1").status in ("TAMPERED", "UNRESOLVED")
    mut = history(tmp_path, anchor, "mut", (mutant,))
    attack(mut)
    got = replay(mut, "t1")
    assert got.status == "VERIFIED", (mutant, got)  # a tamper accepted: the mutant is killed by the corpus, not a unit test
    untouched = history(tmp_path, anchor, "mut2", (mutant,))
    assert replay(untouched, "t1").status == "VERIFIED"  # and the mutant is not simply always-VERIFIED-broken on clean data

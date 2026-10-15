"""P1f-4 capability tokens: attenuation narrows only, tamper/forgery refused, chain_id stable, strict form (known negatives)."""
import base64
import json

import pytest
from r3_shared import extcap as ec

KEY = b"k" * 32


def root(system="WMS", dep="dep1", nonce="n1"):
    return ec.mint_root(KEY, nonce, system, dep)


def per_effect(r=None, **over):
    kw = dict(system="WMS", operation="transfer", target="t1", payload_digest="d" * 64, correlation="r#0", max_uses=1,
              not_after_tick=9)
    kw.update(over)
    return ec.attenuate(r or root(), **kw)


def _edit(cap, fn):
    body = cap[len(ec.PREFIX):]
    d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    fn(d)
    raw = json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    return ec.PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_root_has_only_system_and_deployment_and_no_chain_id():
    r = root()
    assert ec.caveats_of(r) == [("system", "WMS"), ("deployment", "dep1")]
    assert ec.chain_id(r) == "" and ec.verify(KEY, r) == ec.caveats_of(r)


def test_attenuation_appends_and_verifies():
    c = per_effect()
    names = [n for n, _ in ec.caveats_of(c)]
    assert names[:2] == ["system", "deployment"] and set(names[2:]) == set(ec.CAVEATS)
    assert len(ec.verify(KEY, c)) == 9


def test_attenuate_can_only_add_never_remove_or_widen():
    c = per_effect()
    c2 = ec.attenuate(c, max_uses=1, target="t1")
    assert ec.caveats_of(c2)[:len(ec.caveats_of(c))] == ec.caveats_of(c)       # old caveats are a strict prefix
    with pytest.raises(ec.CapError):
        ec.attenuate(c)                                                          # no caveat = no step
    for bad in ({"colour": "red"}, {"max_uses": 0}, {"max_uses": True}, {"not_after_tick": -1}, {"target": ""},
                {"deployment": "x"}):                                           # `deployment` is root-only
        with pytest.raises(ec.CapError):
            ec.attenuate(c, **bad)


def test_chain_id_stable_under_narrowing_and_distinct_across_effects():
    c = per_effect()
    cid = ec.chain_id(c)
    assert len(cid) == 64
    assert ec.chain_id(ec.attenuate(c, not_after_tick=3)) == cid == ec.chain_id(ec.attenuate(ec.attenuate(c, max_uses=1), target="t1"))
    assert ec.chain_id(per_effect(correlation="r#1")) != cid
    assert ec.chain_id(per_effect(root("WMS", "dep2", "n2"))) != cid
    assert ec.chain_id(per_effect(max_uses=99)) != cid                          # different first step = different chain


@pytest.mark.parametrize("mut", [
    lambda d: d["s"][1].remove(d["s"][1][2]),                                    # drop a caveat (widening)
    lambda d: d["s"][1].__setitem__(1, ["operation", "evil"]),                   # edit a caveat
    lambda d: d["s"].insert(1, d["s"].pop(2)),                                   # reorder steps (needs 3 steps)
    lambda d: d.__setitem__("g", "0" * 64),                                       # forged signature
    lambda d: d.__setitem__("n", "other"),                                        # swap the root nonce
    lambda d: (d["s"][1].__delitem__(slice(2, None)), d["s"].insert(2, [["max_uses", 1]]))[0],   # split a step (fresh chain_id attempt)
])
def test_tampered_token_fails_verification(mut):
    c = ec.attenuate(per_effect(), not_after_tick=4)
    with pytest.raises(ec.CapError):
        ec.verify(KEY, _edit(c, mut))


def test_wrong_root_key_and_garbage_refused():
    c = per_effect()
    with pytest.raises(ec.CapError):
        ec.verify(b"x" * 32, c)
    for junk in ("", "nope", ec.PREFIX, ec.PREFIX + "!!!", ec.PREFIX + base64.urlsafe_b64encode(b"{}").decode(), None, 5):
        with pytest.raises(ec.CapError):
            ec.verify(KEY, junk)


def test_root_step_must_be_exact():
    forged = _edit(root(), lambda d: d["s"][0].reverse())
    with pytest.raises(ec.CapError):
        ec.verify(KEY, forged)


def test_validate_cap_form_known_negatives():
    ok = ec.validate_cap(per_effect())
    assert ok["system"] == "WMS" and ok["deployment"] == "dep1" and len(ok["chain_id"]) == 64
    assert ec.validate_cap(root())["chain_id"] == ""
    for bad in (lambda d: d["s"][1].append(["target", 5]), lambda d: d["s"][1].append(["max_uses", True]),
                lambda d: d["s"][1].append(["colour", "red"]), lambda d: d.__setitem__("g", "zz")):
        with pytest.raises(ec.CapError):
            ec.validate_cap(_edit(per_effect(), bad))

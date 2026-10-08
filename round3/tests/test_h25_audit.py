"""Domain-branch audit (A5): renaming checker, static scan, non-vacuity self-test."""
import random

from r3_harness.h25 import audit
from r3_harness.h25.rename import Renamer
from r3_shared.authspec import load_auth_spec
from r3_shared.governance import load_governance
from tests.h25_util import fake


def test_rename_inverse_identity_and_bijection():
    auth, doc = load_auth_spec("manufacturing"), load_governance("polycentric", "manufacturing")
    calls = [{"action": {"kind": "execute", "case": "c1"}}, {"action": {"kind": "propose", "case": "c2", "operation": "x",
                                                                        "args": {"emergency": "em1"}, "on_behalf_of": None}}]
    rn = Renamer(auth, doc, calls, random.Random(1))
    assert len(set(rn.ids.values())) == len(rn.ids)
    assert not any(v.endswith("-1") for v in rn.ids.values())
    assert rn.inv(rn.fwd(doc)) == doc and rn.inv(rn.fwd(auth)) == auth
    assert rn.fwd(doc) != doc and rn.auth(auth) != auth
    assert {"c1", "c2", "em1"} <= set(rn.ids)


def test_oracle_reference_is_renaming_invariant():
    r = audit.rename_audit(fake("fake-honest"), 4, 60, keep_roles=("admin",))
    assert r["domain_branch"] == 0 and r["cases"] == 60


def test_audit_flags_the_domain_branch_mutant_and_scan_is_clean_on_oracle():
    r = audit.rename_audit(fake("fake-domainbranch"), 4, 80, domain="project", keep_roles=("admin",))
    assert r["domain_branch"] > 0
    assert audit.static_scan(sources=fake("fake-domainbranch").sources)["hit_count"] >= 1
    assert audit.static_scan(sources=fake("fake-honest").sources)["hit_count"] == 0


def test_static_scan_flags_each_dispatch_form_and_domain_module_vocabulary():
    voc = {"project", "researcher-1"}
    src = 'def f(d, k):\n    if d == "project":\n        return {"researcher-1": 1}[k]\n    return k in ("project",)\n'
    kinds = {h["kind"] for h in audit.scan_source("x.py", src, voc, False)}
    assert {"compare", "dict-dispatch"} <= kinds
    dm = "from x import grant_table\ndef g(principal):\n    return principal\n"
    assert audit.scan_source("d.py", dm, voc, True)
    assert not audit.scan_source("d.py", "def g(a):\n    return a + 1\n", voc, True)

"""G3 fix5: merit cache on replayed judge calls; G3-E24 A5(c) mechanics (mutant guards, resolutions, module discovery)."""
import json

import pytest

from r3_harness.h25 import audit, boundary
from r3_harness.h25 import replay as RP  # noqa: F401
from tests.h25_util import fake

VOC = {"project", "manufacturing", "none"}
GUARDED = (
    "class V:\n"
    "    def f(self, x):\n"
    "        if 'm1' in self.mutants and self.domain == 'project':\n"
    "            return False\n"
    "        return x\n"
    "    def g(self, b):\n"
    "        return self.mutant('m2') and self.domain == 'project'\n"
    "    def h(self):\n"
    "        return self.domain == 'manufacturing'\n")


def test_merit_is_cached_per_rid_for_replayed_calls(monkeypatch):
    seen = []
    real = RP.replay

    def spy(variant, domain, ops, auth, doc, calls, tag, tr):
        def tr2(c):
            c = tr(c)
            a = c.get("action")
            if isinstance(a, dict) and a.get("kind") == "judge":
                seen.append((c["rid"], a["merit"]))
            return c
        return real(variant, domain, ops, auth, doc, calls, tag, tr2)
    monkeypatch.setattr(boundary.RP, "replay", spy)
    r = None
    for i in range(30):
        seen.clear()
        r = boundary.merit_probe(fake("fake-honest"), 7, i)
        rids = [x for x, _ in seen]
        if len(rids) != len(set(rids)):
            break
    by = {}
    for rid, m in seen:
        by.setdefault(rid, set()).add(m)
    assert len(rids) != len(set(rids)), "no replayed judge call found in 30 cases"
    assert all(len(v) == 1 for v in by.values())
    assert r["fabricated"] is False


def test_mutant_guarded_code_is_scanned_only_when_the_mutant_is_active():
    off = audit.scan_source("v.py", GUARDED, VOC, False)
    assert [h["literal"] for h in off] == ["manufacturing"]
    on1 = audit.scan_source("v.py", GUARDED, VOC, False, active_mutants=("m1",))
    on2 = audit.scan_source("v.py", GUARDED, VOC, False, active_mutants=("m2",))
    assert sorted(h["literal"] for h in on1) == ["manufacturing", "project"]
    assert sorted(h["line"] for h in on2) == [7, 9]


def test_mutant_guard_else_branch_stays_scanned():
    src = "def f(self):\n    if 'm1' in self.mutants:\n        pass\n    else:\n        return self.domain == 'project'\n"
    assert audit.scan_source("v.py", src, VOC, False)


@pytest.mark.parametrize("name", ["paladin", "conventional"])
def test_self_test_mutant_build_is_flagged_and_normal_build_is_not(name):
    pkg = audit.ROUND3 / "src" / name
    base = audit.static_scan(pkg_dir=pkg, resolutions={})
    live = audit.static_scan(pkg_dir=pkg, active_mutants=("domain_privilege_branch",), resolutions={})
    seen = {(h["file"], h["text"]) for h in base["hits"]}
    new = [h for h in live["hits"] if (h["file"], h["text"]) not in seen]
    assert new and all("project" == h["literal"] for h in new)
    assert not any("mutants" in h["text"] or "mutant(" in h["text"] for h in base["hits"])


def test_resolutions_match_whitespace_normalised_and_split_resolved_from_counted(tmp_path):
    srcs = {"a.py": "def f(d):\n    return d  ==   'project'\n\ndef g(d):\n    return d == 'manufacturing'\n"}
    plain = audit.static_scan(sources=srcs, variant="v", resolutions={})
    assert plain["hit_count"] == 2 and plain["resolved_count"] == 0
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"resolutions": [{"variant": "v", "file": "a.py", "scope": "f", "text": "return   d == 'project'", "reason": "wiring"}]}))
    res = audit.load_resolutions(p)
    r = audit.static_scan(sources=srcs, variant="v", resolutions=res)
    assert r["hit_count"] == 1 and r["resolved_count"] == 1 and r["resolved"][0]["reason"] == "wiring"
    assert r["hits"][0]["literal"] == "manufacturing"
    other = audit.static_scan(sources=srcs, variant="w", resolutions=res)  # key includes the variant
    assert other["hit_count"] == 2


def test_missing_resolution_file_means_no_resolutions(tmp_path):
    assert audit.load_resolutions(tmp_path / "absent.json") == {}


def test_domain_modules_are_read_from_variant_py_and_matched_by_path_prefix():
    assert audit.declared_domain_modules(audit.ROUND3 / "src" / "paladin")[0] == "src/paladin/domains/manufacturing/logic"
    assert audit.declared_domain_modules(audit.ROUND3 / "src" / "conventional") == []
    s = audit.static_scan(pkg_dir=audit.ROUND3 / "src" / "paladin", resolutions={})
    dm = [h for h in s["hits"] if h["file"].startswith("src/paladin/domains/")]
    assert dm and all(h["kind"] == "authority-vocabulary" for h in dm)
    assert all(h["kind"] != "authority-vocabulary" for h in s["hits"] if not h["file"].startswith("src/paladin/domains/"))


def test_discovery_cli_lists_hits_with_keys_for_both_variants():
    import subprocess
    import sys
    for v in ("paladin", "conventional"):
        r = subprocess.run([sys.executable, str(audit.ROUND3 / "scripts" / "list_domain_hits.py"), "--variant", v],
                           capture_output=True, text=True, check=True)
        rows = [json.loads(x) for x in r.stdout.splitlines()]
        assert rows and all(len(x["key"]) == 4 and x["key"][0] == v and x["key"][2] == x["scope"] for x in rows)

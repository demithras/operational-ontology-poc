"""G3 fix6: A5(c) hit key includes the enclosing scope (qualname)."""
import json

from r3_harness.h25 import audit

SRC = ("class C:\n    def bindings(self, domain):\n        if domain == 'manufacturing':\n            return 1\n"
       "def boot(domain):\n    if domain == 'manufacturing':\n        return 2\n"
       "X = 1 if Y == 'project' else 2\n")


def _res(tmp_path, entries):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"resolutions": entries}))
    return audit.load_resolutions(p)


def test_hits_carry_scope():
    s = audit.static_scan(sources={"a.py": SRC}, variant="v", resolutions={})
    assert sorted(h["scope"] for h in s["hits"]) == ["<module>", "C.bindings", "boot"]


def test_identical_lines_in_different_functions_resolve_independently(tmp_path):
    t = "if domain == 'manufacturing':"
    res = _res(tmp_path, [{"variant": "v", "file": "a.py", "scope": "boot", "text": t, "reason": "wiring"}])
    s = audit.static_scan(sources={"a.py": SRC}, variant="v", resolutions=res)
    assert [h["scope"] for h in s["resolved"]] == ["boot"]
    assert sorted(h["scope"] for h in s["hits"]) == ["<module>", "C.bindings"]


def test_entry_without_scope_matches_nothing(tmp_path):
    res = _res(tmp_path, [{"variant": "v", "file": "a.py", "text": "if domain == 'manufacturing':", "reason": "x"}])
    assert res == {}
    s = audit.static_scan(sources={"a.py": SRC}, variant="v", resolutions=res)
    assert s["hit_count"] == 3 and s["resolved_count"] == 0


def test_same_full_key_resolves_together(tmp_path):
    src = "def f(d):\n    a = d == 'project'\n    b = d == 'project'\n"
    src = "def f(d):\n    if d == 'project': pass\n    if d == 'project': pass\n"
    res = _res(tmp_path, [{"variant": "v", "file": "a.py", "scope": "f", "text": "if d == 'project': pass", "reason": "r"}])
    s = audit.static_scan(sources={"a.py": src}, variant="v", resolutions=res)
    assert s["resolved_count"] == 2 and s["hit_count"] == 0

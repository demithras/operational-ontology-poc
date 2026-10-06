"""Every authority spec the H23 harness hands to set_authority validates against the authority-spec schema."""
import ast
import copy
from pathlib import Path

import pytest

from r3_harness.h23 import authspecs, corpus as corpus_mod, rules as rules_mod
from r3_harness.h23.corpus import attack_sequence, load_specs
from r3_harness.h23.env import Env
from r3_shared.authspec import validate_auth_spec
from tests.fakes.h23_fakes import FakeVariant

SPECS = load_specs()
SRC = Path(rules_mod.__file__).parent


def rules_calling_set_authority() -> set[str]:
    """Scan the rule table: every `rule == "x"` branch whose body (transitively) calls set_authority."""
    found = set()
    for f in ("rules.py", "approval_rules.py"):
        for node in ast.walk(ast.parse((SRC / f).read_text())):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) \
                    and node.test.left.id == "rule" and isinstance(node.test.comparators[0], ast.Constant):
                body = ast.Module(body=node.body, type_ignores=[])
                if any(isinstance(n, ast.Attribute) and n.attr == "set_authority" for n in ast.walk(body)):
                    found.add(node.test.comparators[0].value)
    return found


def test_scan_finds_the_known_authority_changing_rules():
    assert {"appr_chain", "replay_revoke"} <= rules_calling_set_authority()


def test_every_authority_changing_rule_passes_only_valid_specs(monkeypatch):
    seen: dict[str, list[dict]] = {}
    orig = Env.set_authority
    current = {"rule": None}

    def spy(self, new_auth):
        seen.setdefault(current["rule"], []).append(copy.deepcopy(new_auth))
        return orig(self, new_auth)

    monkeypatch.setattr(Env, "set_authority", spy)
    orig_exe = rules_mod.exe

    def exe(env, step):
        current["rule"] = step["rule"]
        return orig_exe(env, step)

    monkeypatch.setattr(corpus_mod, "exe", exe)
    targets = rules_calling_set_authority()
    for rule in sorted(targets):
        for i in range(60):
            attack_sequence(FakeVariant("correct"), SPECS, 3, i, [rule])
    for rule in targets:
        assert seen.get(rule), f"rule {rule} never reached set_authority; test would be vacuous"
        for spec in seen[rule]:
            validate_auth_spec(spec)
            assert all(g["origin"] in ("round2", "neutral-fix", "neutral-extension") for g in spec["grants"])


def test_helper_rejects_the_old_harness_origin():
    _, auth = SPECS["manufacturing"]
    grant = {"id": "x", "effect": "allow", "operation": "transfer_inventory", "principal": {"id": "planner-1"},
             "resource": {"any": True}, "delegable": False}
    assert authspecs.with_grant(auth, grant)["grants"][-1]["origin"] == "neutral-extension"
    with pytest.raises(Exception):
        authspecs.with_grant(auth, {**grant, "origin": "h23-harness"})
    with pytest.raises(Exception):
        authspecs.checked({**copy.deepcopy(auth), "grants": [{**grant, "origin": "h23-harness"}]})

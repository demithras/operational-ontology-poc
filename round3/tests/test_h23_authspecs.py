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


# ---- P4d: unique ids and strict-loader checks ---------------------------------------------------------------------
import json
import random

from r3_shared.authspec import ROUND3

OPS = {d: json.loads((ROUND3 / "spec" / "ops" / f"{d}.json").read_text()) for d in ("manufacturing", "project")}


def _base(domain="manufacturing"):
    return copy.deepcopy(SPECS[domain][1])


def _g(**kw):
    return {"id": "x1", "effect": "allow", "operation": "transfer_inventory", "principal": {"id": "planner-1"},
            "resource": {"any": True}, "delegable": False, **kw}


def test_base_specs_pass_the_strict_check():
    for d, (_, auth) in SPECS.items():
        authspecs.checked(copy.deepcopy(auth), OPS[d])


def test_with_grant_assigns_unique_ids_when_repeated():
    auth = _base()
    for _ in range(4):
        auth = authspecs.with_grant(auth, _g(), OPS["manufacturing"])
    ids = [g["id"] for g in auth["grants"]]
    assert len(set(ids)) == len(ids) and {"x1", "x1#2", "x1#3", "x1#4"} <= set(ids)


def test_checked_rejects_duplicate_grant_ids():
    auth = _base()
    auth["grants"] += [_g(origin="neutral-extension"), _g(origin="neutral-extension")]
    with pytest.raises(ValueError, match="duplicate grant ids"):
        authspecs.checked(auth)


def test_checked_rejects_duplicate_principal_ids():
    auth = _base()
    auth["principals"].append(copy.deepcopy(auth["principals"][0]))
    with pytest.raises(ValueError, match="duplicate principal"):
        authspecs.checked(auth)


def test_checked_rejects_dangling_delegation_principals():
    auth = _base()
    auth["delegations"].append({"agent": "ghost", "on_behalf_of": "planner-1", "operations": ["transfer_inventory"]})
    with pytest.raises(ValueError, match="unknown principal"):
        authspecs.checked(auth)
    auth = _base()
    auth["delegations"].append({"agent": "agent-1", "on_behalf_of": "ghost", "operations": ["transfer_inventory"]})
    with pytest.raises(ValueError, match="unknown principal"):
        authspecs.checked(auth)


def test_checked_rejects_delegated_by_unknown_principal():
    auth = _base()
    auth["principals"][0]["delegated_by"] = "ghost"
    with pytest.raises(ValueError, match="delegated_by"):
        authspecs.checked(auth)


def test_checked_rejects_grant_for_unknown_principal_id():
    auth = _base()
    auth["grants"].append(_g(principal={"id": "ghost"}, origin="neutral-extension"))
    with pytest.raises(ValueError, match="unknown principal"):
        authspecs.checked(auth)


def test_checked_rejects_approval_operation_missing_from_ops_spec():
    auth = _base()
    auth["grants"].append(_g(operation="approval:nonexistent", origin="neutral-extension"))
    authspecs.checked(copy.deepcopy(auth))  # fine without an ops spec to compare with
    with pytest.raises(ValueError, match="not in the ops spec"):
        authspecs.checked(auth, OPS["manufacturing"])


def test_checked_rejects_delegation_of_unknown_operation_and_duplicate_pairs():
    auth = _base()
    auth["delegations"][0]["operations"].append("no_such_operation")
    with pytest.raises(ValueError, match="not in the ops spec"):
        authspecs.checked(auth, OPS["manufacturing"])
    auth = _base()
    auth["delegations"].append(copy.deepcopy(auth["delegations"][0]))
    with pytest.raises(ValueError, match="duplicate delegation"):
        authspecs.checked(auth)


def test_random_interleaved_authority_rules_always_pass_the_strict_check(monkeypatch):
    seen: list[tuple[dict, dict]] = []
    orig = Env.set_authority

    def spy(self, new_auth):
        seen.append((copy.deepcopy(new_auth), self.ops))
        return orig(self, new_auth)

    monkeypatch.setattr(Env, "set_authority", spy)
    targets = sorted(rules_calling_set_authority())
    rng = random.Random(4)
    for i in range(80):
        pool = [rng.choice(targets) for _ in range(rng.randint(2, 5))]  # repeated and interleaved
        attack_sequence(FakeVariant("correct"), SPECS, 8, i, pool)
    assert len(seen) > 100, "property test would be vacuous"
    multi = 0
    for spec, ops in seen:
        authspecs.checked(spec, ops)
        multi += sum(g["id"].startswith("h23-chain-") for g in spec["grants"]) > 1
    assert multi > 0, "never reached a spec holding two harness-added grants"

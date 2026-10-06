"""Stateful property tests: random call sequences (identities, tools vs direct, on_behalf_of, replays, tampered args,
bad tokens, authority churn). Invariants after EVERY step, measured from the world store, never from return values:
 I1 a non-OK result leaves zero effects;  I2 an OK effect is allowed by an independent oracle written here;
 I3 a request_id commits at most once;     I4 effects only ever come from the conventional service writer."""
import copy
import itertools
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, Phase, settings, strategies as st
import pytest
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule, run_state_machine_as_test

from conv_helpers import MFG_OPS, VALID
from conftest import make_rig
from r3_shared.world import diff

PRINCIPALS = ["planner-1", "junior-1", "supervisor-1", "senior-1", "nobody-1", "admin-1", "agent-1", "agent-hostile-1", "agent-orphan"]
OBO = [None, "planner-1", "junior-1", "admin-1", "nobody-1"]
RES = {"transfer_inventory": ("source_warehouse", "destination_warehouse", "part")}
WH = ["WH-A", "WH-B", "WH-C"]


def oracle_allowed(auth, sub, obo, op, args):
    """Independent reading of the frozen effective-authority rule (PROT-H23.md), plain loops, no shared code."""
    P = {p["id"]: p for p in auth["principals"]}
    res = []
    if op == "transfer_inventory":
        res = [("Warehouse", args.get("source_warehouse")), ("Warehouse", args.get("destination_warehouse")),
               ("Part", args.get("part"))]

    def sel_ok(sel, pid):
        p = P[pid]
        if sel.get("any"):
            return True
        if "role" in sel:
            return sel["role"] in p["roles"]
        if "id" in sel:
            return sel["id"] == pid
        have = [k for t, k in res if t == sel["on_type"]]
        return bool(have) and all({"type": sel["on_type"], "key": k, "relation": sel["relation"]} in p["relations"] for k in have)

    def grants(pid, effect):
        return [g for g in auth["grants"] if g["effect"] == effect and sel_ok(g["principal"], pid)
                and (g["operation"] in (op, "*")) and (g["resource"].get("any") or any(t == g["resource"].get("type") for t, _ in res))]

    if sub not in P:
        return False
    if obo is None:
        return bool(grants(sub, "allow")) and not grants(sub, "deny")
    if obo not in P or not any(d["agent"] == sub and d["on_behalf_of"] == obo and op in d["operations"] for d in auth["delegations"]):
        return False
    if grants(sub, "deny") or grants(obo, "deny"):
        return False
    return any(g["delegable"] for g in grants(sub, "allow")) and bool(grants(obo, "allow"))


STATS = {"committed": 0, "refused": 0}


class Sequences(RuleBasedStateMachine):
    MUTANTS: tuple = ()

    def __init__(self):
        super().__init__()
        self.rig = make_rig(Path(tempfile.mkdtemp()), "manufacturing", self.MUTANTS)
        self.auth = self.rig.auth
        self.committed: dict[str, tuple] = {}
        self.ids = itertools.count()
        self.last = self.rig.snap()
        self.alive = True

    @rule(who=st.sampled_from(PRINCIPALS + ["planner-1"] * 3 + ["admin-1"] * 2), op=st.sampled_from(MFG_OPS), obo=st.sampled_from(OBO + [None] * 3),
          via=st.sampled_from(["call_tool", "direct"]), src=st.sampled_from(WH), dst=st.sampled_from(WH),
          qty=st.integers(-1, 30), reuse=st.booleans(),
          junk=st.sampled_from([None] * 9 + ["principal", "actor", "onHand", "owner"]),
          bad_token=st.sampled_from([None] * 8 + ["forged", "wrong_aud"]))
    def call(self, who, op, obo, via, src, dst, qty, reuse, junk, bad_token):
        args = copy.deepcopy(VALID[op])
        if op == "transfer_inventory":
            args.update(source_warehouse=src, destination_warehouse=dst, quantity=qty)
        if junk:
            args[junk] = "admin-1"
        tok = self.rig.token(who)
        if bad_token == "forged":
            tok = tok[:-3] + "abc"
        elif bad_token == "wrong_aud":
            tok = self.rig.token(who, aud="paladin")
        rid = f"r{next(self.ids) // (2 if reuse else 1)}"
        r = getattr(self.rig.dep, via)(tok, op, args, on_behalf_of=obo, request_id=rid)
        after = self.rig.snap()
        eff = diff(self.last, after)
        self.last = after
        if r.status != "OK":
            STATS["refused"] += 1
            assert eff == [], (r, eff)                                   # I1
            return
        assert not bad_token and not junk, (r, who)                      # forged/expired/identity-smuggling never succeed
        if eff:
            assert oracle_allowed(self.auth, who, obo, op, args), (who, obo, op, args, r)   # I2
            assert rid not in self.committed                              # I3
            self.committed[rid] = (who, obo, op, args)
            STATS["committed"] += 1
            assert all(e["kind"] == "external" and e["writer"] == "conventional-service" for e in eff)   # I4

    @rule()
    def tick(self):
        if self.rig.clock.now() < 5:  # evidence freshness window is 5 ticks: do not let time alone refuse everything
            self.rig.clock.advance(1)

    @rule(drop=st.sampled_from(["none", "transfer_inventory", "expedite_purchase_order"]))
    def churn_authority(self, drop):
        a = copy.deepcopy(self.rig.auth)
        if drop != "none":
            a["grants"] = [g for g in a["grants"] if g["operation"] not in (drop, "*")]
        self.auth = a
        self.rig.dep.set_authority(a)

    @invariant()
    def unique_idempotency_keys(self):
        keys = [e["idempotency_key"] for e in self.last["effects"] if e["idempotency_key"]]
        assert len(keys) == len(set(keys))


TestSequences = Sequences.TestCase
TestSequences.settings = settings(max_examples=40, stateful_step_count=20, deadline=None,
                                  suppress_health_check=list(HealthCheck))


SETTINGS = settings(max_examples=40, stateful_step_count=20, deadline=None, suppress_health_check=list(HealthCheck),
                    derandomize=True)


def test_campaign_is_not_vacuous():
    run_state_machine_as_test(Sequences, settings=SETTINGS)
    assert STATS["committed"] >= 10 and STATS["refused"] >= 100, STATS  # both outcome classes were exercised


@pytest.mark.parametrize("mutant", ["identity_substitution", "backstop_bypass"])
def test_known_negative_campaign_kills_the_mutant(mutant):
    """The property campaign itself detects planted bugs (mutation proof for the sequence suite)."""
    machine = type("M_" + mutant, (Sequences,), {"MUTANTS": (mutant,)})
    with pytest.raises(AssertionError):
        run_state_machine_as_test(machine, settings=settings(max_examples=150, stateful_step_count=25, deadline=None,
                                                             suppress_health_check=list(HealthCheck), database=None,
                                                             phases=[Phase.generate]))  # kill detection only: no shrinking

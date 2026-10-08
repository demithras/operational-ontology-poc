"""R10 concurrency safety (PROT-H23-A8): >= 8 threads; effects equal some serial order; the unsynchronized mutant breaks it."""
import threading

from conv_helpers import VALID
from r3_shared.world import diff

TRANSFER = {**VALID["transfer_inventory"], "destination_warehouse": "WH-C"}
THREADS = 8


def _race(fns):
    barrier, out = threading.Barrier(len(fns)), [None] * len(fns)

    def run(i):
        barrier.wait()
        out[i] = fns[i]()

    ts = [threading.Thread(target=run, args=(i,)) for i in range(len(fns))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


def _same_request_id(rig):
    tok = rig.token("planner-1")
    return _race([lambda: rig.dep.direct(tok, "transfer_inventory", TRANSFER, request_id="same") for _ in range(THREADS)])


def test_same_request_id_from_many_threads_commits_once(mfg):
    before = mfg.snap()
    res = _same_request_id(mfg)
    assert {r.status for r in res} == {"OK"}
    assert sum(1 for r in res if not r.body.get("replayed")) == 1
    assert len(diff(before, mfg.snap())) == 1


def _supersede_race(rig):
    toks = {w: rig.token(w) for w in ("researcher-1", "researcher-2")}
    calls = [lambda i=i: rig.dep.direct(toks["researcher-1" if i % 2 else "researcher-2"], "supersede_hypothesis",
                                        {"hypothesis": "H-D", "successor": "H-E" if i % 2 else "H-A"}, request_id=f"s{i}")
             for i in range(THREADS)]
    return _race(calls)


def _links(effects):
    return sorted(e["ref"] for e in effects if e["ref"].startswith("SUPERSEDED_BY|"))


# hand-written serial outcomes: whichever request runs first wins, every later one fails its phase precondition
SERIAL_LINKS = ([f"SUPERSEDED_BY|Hypothesis:H-D|Hypothesis:H-E"], [f"SUPERSEDED_BY|Hypothesis:H-D|Hypothesis:H-A"])


def test_conflicting_supersedes_equal_some_serial_order(proj):
    before = proj.snap()
    res = _supersede_race(proj)
    # G3-E17: the later requests fail the deny rule (illegal lifecycle transition) before any precondition
    assert sorted(r.status for r in res) == ["DENIED"] * (THREADS - 1) + ["OK"]
    eff = diff(before, proj.snap())
    assert _links(eff) in SERIAL_LINKS and len(eff) == 2
    phase = next(e for e in eff if e["ref"] == "Hypothesis:H-D")
    assert phase["changes"]["phase"] == ["EVALUATED", "SUPERSEDED"]


def test_repeated_races_stay_serial(make):
    for _ in range(5):
        rig = make("project")
        before = rig.snap()
        _supersede_race(rig)
        assert _links(diff(before, rig.snap())) in SERIAL_LINKS


def test_mutant_unsynchronized_commit_double_commits_same_request_id(make):
    rig = make("manufacturing", ["unsynchronized_commit"])
    before = rig.snap()
    _same_request_id(rig)
    assert len(diff(before, rig.snap())) > 1  # the clean variant commits exactly once (test above)


def test_mutant_unsynchronized_commit_breaks_serializability(make):
    rig = make("project", ["unsynchronized_commit"])
    before = rig.snap()
    res = _supersede_race(rig)
    links = _links(diff(before, rig.snap()))
    assert links not in SERIAL_LINKS or sum(r.status == "OK" for r in res) > 1

"""In-process H28 corpus runner for tests: private ExternalWorld, fake/real variant factory, judge + aggregate."""
import tempfile
from pathlib import Path

from r3_harness.h28 import finalize, runner, worlds


def run_corpus(factory, cases=130, controls=14, seed=2811, observer_factory=None, mutants=()):
    d = Path(tempfile.mkdtemp(prefix="h28t"))
    pair = worlds.Pair(d, "r3t", seed=False)                  # G4-E26: main world + twin world
    try:
        pre = runner.run_variant(factory, "t", d / "out", "exp-t-dev-1", seed, pair.main.sock_path, pair.main.ctl_path, str(d / "ext"),
                                 twin_sock=pair.twin.sock_path, twin_ctl=pair.twin.ctl_path, twin_dir=str(d / worlds.TWIN_DIR),
                                 cases=cases, controls=controls, observer_factory=observer_factory, mutants=mutants)
    finally:
        closed = pair.close()["external"]
    J = finalize.judge_all(d / "out", str(d / "ext"), pre, str(d / worlds.TWIN_DIR))
    return J, finalize.aggregate(J), closed, pre

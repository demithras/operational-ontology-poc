"""Make Hypothesis generation independent of the set of project modules that happen to be loaded.

Since Hypothesis 6.131 the data generator mixes into integers/floats/bytes/text the literals harvested from every
local, non-test module in sys.modules. A fixed seed therefore does NOT fix the corpus: importing one more source module
(or editing one literal) changes it. Inside this context the local-constants pool is empty, so a corpus depends only on
(seed, strategy code, Hypothesis version)."""
from __future__ import annotations

from contextlib import contextmanager

LAST = {"isolated": False}


@contextmanager
def isolated_constants():
    try:
        import hypothesis.internal.conjecture.providers as prov
        orig, empty = prov._get_local_constants, prov.Constants()
    except (ImportError, AttributeError):  # other Hypothesis layout: report that isolation was not applied
        LAST["isolated"] = False
        yield False
        return
    prov._get_local_constants = lambda: empty
    prov.CONSTANTS_CACHE.cache.clear()
    LAST["isolated"] = True
    try:
        yield True
    finally:
        prov._get_local_constants = orig
        prov.CONSTANTS_CACHE.cache.clear()

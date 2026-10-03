"""Meaning rule (protocol/H15_V2_PREREG.json): the bounded-vocabulary test. Known-positive: the v2 candidate stays
within its frozen phrase table at every package size. Known-negative: the v1 encoding (enumerated 'pi X Y' labels)
FAILS the same test -- the number of distinct phrases grows with package size."""
import pytest

import eoo_openpona
import eoo_openpona2
from eoo_h15 import corpus, meaning

from openpona_util import load


@pytest.fixture(scope="module")
def packages():
    pk = []
    corpus.generate(120, 11, lambda i, p: pk.append((f"generated[{i}]", p)))
    return pk + [(d, load(f"domains/{d}/ir.json")) for d in ("manufacturing", "project")]


def test_v2_is_bounded_by_its_phrase_table(packages):
    r = meaning.bounded_vocabulary(eoo_openpona2.render, packages, meaning.v2_table_size())
    assert r["ok"] and not r["sizes_over_bound"], r["per_size"]
    big = [x for x in r["per_size"] if x["size"] >= 90]
    assert big and all(x["max_distinct_per_package"] <= meaning.v2_table_size() for x in big)


def test_v1_known_negative_fails_the_test(packages):
    r = meaning.bounded_vocabulary(eoo_openpona.render, packages, meaning.v1_table_size())
    assert not r["ok"] and r["sizes_over_bound"], "the bounded-vocabulary test has no teeth"
    assert r["distinct_phrases_total"] > 3 * meaning.v1_table_size()
    sizes = [x for x in r["per_size"] if x["packages"]]
    assert sizes[-1]["max_distinct_per_package"] > sizes[len(sizes) // 2]["max_distinct_per_package"]  # grows


def test_label_injection_known_negative(packages):
    """A v2 render with one enumerated label per resource (what the rule forbids) must fail too."""
    def labelled(ir):
        text, rec = eoo_openpona2.render(ir)
        out, n = [], 0
        for ln in text.splitlines():
            if ln.endswith(" ni li lon") and not ln.startswith(("kulupu", "tenpo", "ma ")):
                n += 1
                ln = ln.replace(" ni li lon", f" pi {['open', 'lon', 'tawa'][n % 3]} {['wile', 'pali', 'pilin'][n // 3 % 3]}"
                                f"{' pi sike ale' * (n // 9)} li lon")
            out.append(ln)
        return "\n".join(out), rec
    r = meaning.bounded_vocabulary(labelled, packages, meaning.v2_table_size())
    assert not r["ok"]


def test_per_size_report_shape(packages):
    r = meaning.bounded_vocabulary(eoo_openpona2.render, packages[:10], meaning.v2_table_size())
    row = r["per_size"][0]
    assert set(row) >= {"size", "packages", "mean_distinct_per_package", "max_distinct_per_package",
                        "distinct_in_group", "cumulative_distinct_up_to_size"}

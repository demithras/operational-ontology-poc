"""H15 v2 surface: the frozen phrase table, line acceptance, no labels, no new tokens, domain renders."""
import json
import re
import subprocess
import sys

import openpona
from openpona.parser import parse

import eoo_openpona2 as op2
from eoo_openpona2 import Invalid
from eoo_openpona2.lines import expected_skeleton, read_line
from eoo_openpona2.phrases import T
from eoo_openpona2.table import lines, table_size

from openpona_util import ROOT, load

DOMAINS = ("manufacturing", "project")


def test_every_concrete_table_line_parses_resolved_with_the_assumed_skeleton():
    bad = []
    for text in lines():
        r = parse(text)
        if r.status != "RESOLVED" or r.skeletons != [expected_skeleton(r.tokens)]:
            bad.append((text, r.status, r.skeletons))
    assert not bad, bad[:5]
    assert table_size() == len(lines()) and 0 < table_size() < 400


def test_table_uses_only_pinned_tokens_and_never_two_adjacent_ni():
    toks = {t for text in lines() for t in text.split()}
    assert toks <= set(openpona.TOKENS), toks - set(openpona.TOKENS)
    assert not any(" ni ni" in text for text in lines())


def test_no_label_groups_every_pi_group_is_a_canon_binding():
    """Meaning rule: no phrase exists to tell resources apart. The only `pi` groups are possessive bindings
    'pi <head> ni' (of this entity / of this package); there is no enumerated 'pi X Y' label anywhere."""
    for text in lines():
        toks = text.split()
        for i, t in enumerate(toks):
            if t == "pi":
                assert toks[i + 2] == "ni" and toks[i + 1] in ("ijo", "linja", "lukin", "kulupu"), text


def test_every_row_has_a_gloss_and_strength():
    for rid, (pat, meaning, gloss, strength) in T.items():
        assert pat and meaning and len(gloss) > 8 and strength in ("strong", "moderate", "weak"), rid


def test_a_line_outside_the_table_is_invalid_even_if_it_parses():
    assert parse("ijo ni li pona").status == "RESOLVED"
    try:
        read_line(1, "ijo ni li pona")
    except Invalid as e:
        assert e.code == "unknown_line"
    else:
        raise AssertionError("accepted a line that is not in the phrase table")


def test_v1_label_lines_are_not_v2_lines():
    v1 = (ROOT / "domains/manufacturing/openpona.op").read_text().splitlines()
    assert v1 and not any(ln in lines() for ln in v1 if " pi " in ln)


def test_domain_renders_are_committed_and_round_trip_exactly():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/build_openpona2_domains.py"), "--check"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    for d in DOMAINS:
        ir = load(f"domains/{d}/ir.json")
        text = (ROOT / f"domains/{d}/openpona2.op").read_text()
        rec = op2.load_record((ROOT / f"domains/{d}/openpona2.record.json").read_text())
        out = op2.compile(text, rec)
        assert json.dumps(out, sort_keys=True) == json.dumps(ir, sort_keys=True), d
        assert all(ln in lines() for ln in text.splitlines())


def test_record_keys_are_neutral_positional_addresses():
    key = re.compile(r"L[1-9][0-9]*\.a[1-9][0-9]*")
    for d in DOMAINS:
        rec = json.loads((ROOT / f"domains/{d}/openpona2.record.json").read_text())
        assert rec and all(key.fullmatch(k) for k in rec) and all(isinstance(v, str) for v in rec.values())


def test_encoding_doc_and_cases_are_generated_from_the_table():
    for script in ("build_openpona2_encoding.py", "build_openpona2_ambiguity_cases.py"):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--check"], capture_output=True, text=True,
                           timeout=300)
        assert r.returncode == 0, script + r.stdout + r.stderr


def test_gaps_file_is_a_list_with_known_detectors():
    from eoo_openpona2 import gaps
    data = json.loads((ROOT / "ontology/openpona2_gaps.json").read_text())
    assert isinstance(data, list) and gaps.gaps() == data

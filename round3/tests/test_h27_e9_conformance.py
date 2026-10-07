"""E-9 shared conformance: for generated edge cases of every mutating kind, run each against BOTH real variants (registry,
with history + anchor) and assert  variant wrote an envelope  <=>  not oracle_schema_invalid(...).
Envelope presence is observed in the history store (content scan), never from the call result."""
import os
import shutil
import tempfile

import pytest

from r3_harness.h27 import layout
from r3_harness.h27.gen_history import to_v2
from r3_harness.h27.stream import Stream, oracle_schema_invalid
from r3_shared import registry
from r3_shared.anchor import AnchorClient, start_anchor
from r3_shared.authspec import load_auth_spec
from r3_shared.opsspec import load_ops_spec

from test_h27_e9_cases import edge_cases, op_cases, revoke_cases

DOMAINS = ("manufacturing", "project")
MIN_CASES = 200
KINDS = ("call_tool", "direct", "approve", "delegate", "revoke")


@pytest.fixture(scope="module")
def anchor():
    if os.environ.get("R3_ANCHOR_SOCK"):  # started by scripts/run_sandboxed.sh
        yield AnchorClient(os.environ["R3_ANCHOR_SOCK"])
        return
    sockdir = tempfile.mkdtemp(prefix="anc")
    ap = start_anchor(os.path.join(sockdir, "adir"), os.path.join(sockdir, "s"))
    yield ap.client()
    if ap.proc.poll() is None:
        ap.proc.kill()
    shutil.rmtree(sockdir, ignore_errors=True)


def n_env(stream) -> int:
    return sum(len(v) for v in layout.scan(stream.view).envs.values())


def make_stream(name, domain, anchor, tmp_path):
    ops, auth = load_ops_spec(domain), to_v2(load_auth_spec(domain), load_ops_spec(domain))
    variant = registry.load_variant(name)
    s = Stream(variant, domain, ops, auth, str(tmp_path / f"{name}-{domain}"), anchor, tag=f"e9{name}{domain}")
    s.auth = {k: v for k, v in auth.items() if k not in ("capabilities", "revoked")}
    return s


def principals(s):
    hum = [p["id"] for p in s.auth["principals"] if p["kind"] == "human" and not p.get("delegated_by")]
    return hum[0], hum[1]


def run_one(s, kind, subject, op, args, requester):
    tok, rid = s.token(subject), s.rid()
    before = n_env(s)
    try:
        if kind == "call_tool":
            s.dep.call_tool(tok, op, args, None, rid)
        elif kind == "direct":
            s.dep.direct(tok, op, args, None, rid)
        elif kind == "approve":
            s.dep.approve(tok, op, args, requester, None)
        elif kind == "delegate":
            s.dep.delegate(tok, args, rid)
        else:
            s.dep.revoke(tok, args, rid)
    except Exception:  # noqa: BLE001 - a raise is "no envelope" unless one was written (observed below)
        pass
    return n_env(s) > before


def cases_for(kind, ops_by_dom):
    if kind in ("delegate", "revoke"):
        return [(None, lab, None, a) for lab, a in (edge_cases(n_ids=80) if kind == "delegate" else revoke_cases())]
    return [(d, lab, op, a) for d, ops in ops_by_dom.items() for lab, op, a in op_cases(ops)]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("name", ["paladin", "conventional"])
def test_envelope_iff_not_schema_invalid(name, kind, anchor, tmp_path):
    ops_by_dom = {d: load_ops_spec(d) for d in DOMAINS}
    cs = cases_for(kind, ops_by_dom)
    assert len(cs) >= MIN_CASES, len(cs)
    streams, mism, valid_n, invalid_n = {}, [], 0, 0
    for dom, label, op, args in cs:
        d = dom or "manufacturing"
        if d not in streams:
            streams[d] = make_stream(name, d, anchor, tmp_path)
        s = streams[d]
        a, b = principals(s)
        want_env = not oracle_schema_invalid(s.ops, kind, op, args)
        valid_n += want_env
        invalid_n += not want_env
        got = run_one(s, kind, a, op, args, b)
        if got != want_env:
            tag = ""
            if kind == "approve" and op in {o["name"] for o in s.ops["operations"] if not o.get("approval")}:
                tag = " [op takes no approval]"  # variant refuses INVALID 'takes no approval' without envelope; E-9 lists it as governed
            mism.append(f"{d}/{label}: envelope={got} expected={want_env}{tag}")
    assert valid_n >= 5 and invalid_n >= 20, (valid_n, invalid_n)  # both classes exercised
    assert not mism, f"{name}/{kind}: {len(mism)} of {len(cs)} cases mismatch E-9:\n" + "\n".join(mism[:400])

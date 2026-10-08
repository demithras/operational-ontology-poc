"""Per-observation judging against the ORACLE (read/tools/provenance correctness, canary scan, form check).
Returns class tags; the pair comparison (noninterference) lives in observe.py."""
from __future__ import annotations

from r3_oracle import disclosure_prov as P, disclosure_reads as R
from r3_shared.disclosure import check_low_result, is_marker

READ_M = ("read_object", "list_objects", "list_links", "query")


def compare_decision(exp: dict, got: dict, truth: dict) -> list[str]:
    """Field-level verdict of a decision view vs the oracle's expected redacted view (G3-E7)."""
    out = []
    for k, e in exp.items():
        g = got.get(k, "<missing>")
        if g == e:
            continue
        if is_marker(g) and not is_marker(e):
            out.append(f"over_redaction:{k}")
        elif is_marker(e) and not is_marker(g):
            out.append(f"provenance_overdisclosure:{k}" if g == truth.get(k) else f"false_provenance:{k}")
        elif k == "authority_path" and isinstance(g, list) and isinstance(e, list):
            if len(g) == len(e) and all(x == y or (is_marker(y) and not is_marker(x) and x == t)
                                        for x, y, t in zip(g, e, truth["authority_path"])):
                out.append("provenance_overdisclosure:authority_path")
            elif any(is_marker(y) and not is_marker(x) for x, y in zip(g, e)):
                out.append("provenance_overdisclosure:authority_path")
            else:
                out.append("false_provenance:authority_path")
        else:
            out.append(f"false_provenance:{k}")
    out += [f"false_provenance:extra:{k}" for k in got if k not in exp]
    return out


def judge_prov(lv, item: dict, res) -> list[str]:
    m = item["m"]
    if m == "prov_decision":
        st, body = P.expected_prov_decision(lv, item["id"])
        if (res.status, res.body) == (st, body):
            return []
        if st != "OK" or res.status != "OK":
            return ["provenance_overdisclosure:existence" if st != "OK" else "over_redaction:whole"]
        d = P.find_decision(lv, item["id"])
        return compare_decision(body["decision"], res.body.get("decision", {}), d["scalars"]) + \
            ([] if res.body.get("partial") is True else ["false_provenance:partial"])
    if m == "prov_object":
        st, body = P.expected_prov_object(lv, item["ref"])
        return [] if (res.status, res.body) == (st, body) else ["false_provenance:prov_object"]
    st, body = P.expected_authority_used_as(lv, item["rid"])
    if (res.status, res.body) == (st, body):
        return []
    if st != "OK" or res.status != "OK":
        return ["provenance_overdisclosure:existence" if st != "OK" else "over_redaction:whole"]
    d = next(x for x in lv.facts.decisions if x.get("rid") == item["rid"])
    tags = [t for t in compare_decision({"authority_path": body["path"]}, {"authority_path": res.body.get("path")},
                                        {"authority_path": d["edge_path"]})]
    tags += [f"false_provenance:{k}" for k in body if k != "path" and res.body.get(k) != body[k]]
    return tags


def judge_tools(lv, got: list, auth, ops, edges) -> dict:
    exp = R.expected_tools(auth, ops, lv.observer, edges)
    en, gn = {r["name"]: r["input_schema"] for r in exp}, {t.name: t.input_schema for t in got}
    return {"hidden_capability": sorted(set(gn) - set(en)), "exposure_loss": sorted(set(en) - set(gn)),
            "schema_disclosure": sorted(n for n in set(gn) & set(en) if gn[n] != en[n])}


def judge_read(lv, item: dict, res):
    """(mismatch: bool | None) None = the oracle has no frozen answer for this call."""
    m = item["m"]
    exp = {"read_object": lambda: R.expected_read_object(lv, item.get("ref")),
           "list_objects": lambda: R.expected_list_objects(lv, item.get("type")),
           "list_links": lambda: R.expected_list_links(lv, item.get("ref"), item.get("lt")),
           "query": lambda: R.expected_query(lv, item["name"], item["args"])}[m]()
    if exp is None:
        return None
    return (res.status, res.body) != exp


def form_ok(m: str, res) -> str | None:
    try:
        check_low_result(m, res)
    except ValueError as exc:
        return str(exc)[:120]
    return None

"""Optional semantic check (NOT part of validity): do implementing object types actually satisfy their interface?

An object type that ``implements`` an interface must declare every interface required property with the same
name and type, and every interface required link must touch the interface or the implementer. The frozen schema
does not require this, so generated packages are not held to it; the real-domain IR files are.
"""
from __future__ import annotations


def interface_conformance_errors(pkg: dict) -> list[str]:
    errs = []
    ifaces = {i["id"]: i for i in pkg["interfaces"]}
    links = {lk["id"]: lk for lk in pkg["link_types"]}
    for o in pkg["object_types"]:
        props = {p["name"]: p for p in o["properties"]}
        for iid in o["implements"]:
            i = ifaces.get(iid)
            if i is None:
                continue
            for rp in i["required_properties"]:
                got = props.get(rp["name"])
                if got is None:
                    errs.append(f"{o['id']} implements {iid} but lacks property {rp['name']!r}")
                elif got["type"] != rp["type"]:
                    errs.append(f"{o['id']}.{rp['name']} has type {got['type']!r}, interface {iid} requires {rp['type']!r}")
            for rl in i["required_links"]:
                lk = links.get(rl)
                if lk is None or not ({lk["from"], lk["to"]} & {iid, o["id"]}):
                    errs.append(f"{o['id']} implements {iid} but required link {rl!r} touches neither")
    return errs

"""P6 audit item (a): the tool surface of a delegate honours its delegation entry's operation list."""


def test_delegate_tools_are_limited_to_the_delegation_operations(mfg):
    names = lambda: {t.name for t in mfg.dep.tools(mfg.token("agent-1"))}
    assert names() == {"transfer_inventory"}
    narrowed = {**mfg.auth, "delegations": [
        {**d, "operations": ["expedite_purchase_order"]} if d["agent"] == "agent-1" else d for d in mfg.auth["delegations"]]}
    mfg.dep.set_authority(narrowed)
    assert "transfer_inventory" not in names()  # still granted via the delegator, but not delegated to this agent
    r = mfg.dep.call_tool(mfg.token("agent-1"), "transfer_inventory",
                          {"source_warehouse": "WH-B", "destination_warehouse": "WH-C", "part": "PX-17", "quantity": 10},
                          on_behalf_of="planner-1", request_id="x")
    assert r.status == "DENIED"

"""Gate 4 test adapters (Paladin side): a recorder and the minimal Byzantine primitives the Paladin tests need.
(The frozen catalogue H0..G3 belongs to the H28 harness; these follow the same ids and behaviour.)"""
from __future__ import annotations

from r3_shared.extadapter import AdapterReply


class Recorder:
    def __init__(self, inner):
        self.inner, self.adapter_id, self.log = inner, inner.adapter_id, []

    def submit(self, req):
        self.log.append(req)
        return self.inner.submit(req)


class Honest:
    adapter_id = "H0"

    def __init__(self, client):
        self.client = client

    def submit(self, req):
        r = self.client.write(req.cap, req.operation, req.target, req.payload, self.adapter_id)
        return AdapterReply("OK" if r.status == "applied" else "FAILED", {"seq": r.seq})


class FalseSuccess(Honest):          # L1: no write, reply OK
    adapter_id = "L1"

    def submit(self, req):
        return AdapterReply("OK", {"observed": {"transferStatus": "COMMITTED"}})


class FalseFailure(Honest):          # L2: write applied, reply FAILED
    adapter_id = "L2"

    def submit(self, req):
        super().submit(req)
        return AdapterReply("FAILED", {})


class TimeoutAfterApply(Honest):     # L3: applied, then raise (first call only)
    adapter_id = "L3"

    def __init__(self, client):
        super().__init__(client)
        self.calls = 0

    def submit(self, req):
        self.calls += 1
        r = super().submit(req)
        if self.calls == 1:
            raise TimeoutError("timeout after apply")
        return r


class TargetSubstitution(Honest):    # T1
    adapter_id = "T1"

    def submit(self, req):
        self.client.write(req.cap, req.operation, req.target + "-evil", req.payload, self.adapter_id)
        return AdapterReply("OK", {})


class PayloadMutation(Honest):       # T2
    adapter_id = "T2"

    def submit(self, req):
        self.client.write(req.cap, req.operation, req.target, {**req.payload, "mutated": 1}, self.adapter_id)
        return AdapterReply("OK", {})


class Duplicate(Honest):             # R1: the same write three times
    adapter_id = "R1"

    def submit(self, req):
        for _ in range(3):
            r = self.client.write(req.cap, req.operation, req.target, req.payload, self.adapter_id)
        return AdapterReply("OK", {})


class Omission(Honest):              # O1
    adapter_id = "O1"

    def submit(self, req):
        return AdapterReply("TIMEOUT", {})


class PolicyReply(Honest):           # G1/G2: policy- and authority-shaped replies around an honest write
    adapter_id = "G2"

    def submit(self, req):
        super().submit(req)
        return AdapterReply("OK", {"approval": {"approver": "senior-1", "request": req.request_id}, "grant": "admin",
                                   "on_behalf_of": "planner-1", "decision": "approved", "policy": "waived"})


class Broadening(Honest):            # E5: tries to write ANOTHER target with whatever cap it gets (scope attack)
    adapter_id = "T1"

    def submit(self, req):
        self.client.write(req.cap, req.operation, "po:PO-OTHER", req.payload, self.adapter_id)
        return AdapterReply("OK", {})

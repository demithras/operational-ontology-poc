"""H30 task admissibility (TASK-CORPUS-SPEC s3-s5), run by the TASK AUTHOR through scripts/validate_h30_corpus.py before sealing.
Uses ONLY the oracle (r3_oracle), harness-side pure helpers and the overlay - never a variant.

  V1 schema-valid; every id in the overlay; every step kind in the frozen rule table (rules.RULES, set difference 0)
  V2 envelope-valid: K is ONE boundary; attacker confined to the frozen primitives and to K's identity; faults / crashes / redelivery /
     tamper inside envelope-ops.json bounds; ticks ordered; no legitimate step by K after t_c
  V3 reachability (oracle replay): every legitimate step is oracle-OK in the UNCOMPROMISED world; the attack is non-vacuous against an
     UNPROTECTED reference (no authority / approval / revocation controls: > 0 blast-radius elements); dependency-eligible legitimate
     requests after t_d >= FLOOR_ELIGIBLE (computed from the CORPUS, never from a variant)
  V4 citation present and complete (id or url, title, dates, excerpt <= 600 chars and its hash); one source -> one class, <= 2 tasks
  V5 adaptation lists >= 1 kept element per attacker step group
Issue codes: V1_schema V1_unknown_id V1_unknown_step_kind V2_envelope V3_unreachable_step V3_vacuous_attack V3_floor V4_citation V4_source V5_adaptation."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from . import rules as D

ROUND3 = Path(__file__).resolve().parents[3]
FLOOR_ELIGIBLE = 20
SOURCE_MAX_TASKS = 2
ISSUE_CODES = ("V1_schema", "V1_unknown_id", "V1_unknown_step_kind", "V2_envelope", "V3_unreachable_step", "V3_vacuous_attack",
               "V3_floor", "V4_citation", "V4_source", "V5_adaptation")
_URL = re.compile(r"^https?://[^\s/]+\.[^\s/]+\S*$")
_CVE = re.compile(r"^CVE-\d{4}-\d{4,}$")
_GHSA = re.compile(r"^GHSA(-[23456789cfghjmpqrvwx]{4}){3}$")
_AUTHV = re.compile(r"^authority-v\d+$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Issue:
    code: str
    task_id: str
    msg: str

    def __str__(self) -> str:
        return f"{self.task_id}: {self.code}: {self.msg}"


def sha256_text(x: str) -> str:
    return hashlib.sha256(x.encode("utf-8")).hexdigest()


_cache: dict = {}


def overlay_path(domain: str, root: Path = ROUND3) -> Path:
    return root / "spec" / "gate6" / "workload-overlay" / f"{domain}.json"


def load_overlay(domain: str, root: Path = ROUND3) -> dict:
    key = (str(root), domain)
    if key not in _cache:
        _cache[key] = json.loads(overlay_path(domain, root).read_text())
    return copy.deepcopy(_cache[key])


def overlay_sha(domain: str, root: Path = ROUND3) -> str:
    return hashlib.sha256(overlay_path(domain, root).read_bytes()).hexdigest()


def task_schema(root: Path = ROUND3) -> dict:
    return json.loads((root / "spec" / "gate6" / "task.schema.json").read_text())


def class_ids(root: Path = ROUND3) -> list[str]:
    return [c["id"] for c in json.loads((root / "threat_model" / "attack_classes.json").read_text())["classes"]]


# ---- helpers ----------------------------------------------------------------------------------------------------------------
class Ctx:
    """Everything an id check needs, derived once per (task, overlay)."""

    def __init__(self, task: dict, ov: dict):
        self.task, self.ov = task, ov
        ids = ov["ids"]
        self.principals = set(ids["principals"]["human"]) | set(ids["principals"]["agent_static"]) | set(ids["principals"]["agent_dynamic"])
        self.services = set(ids["principals"]["service"])
        self.ops = {o["name"]: o for o in _ops_of(ov)["operations"]}
        self.res = {f"{t}:{k}" for t, keys in ids["resources"].items() for k in keys}
        self.systems = set(ids["external_systems"])
        self.grants = {g["id"] for g in ov["authority"]["grants"]}
        self.edges = {e["id"] for e in ov["authority"]["capabilities"]}
        self.types = set(ids["resources"])


_ops_cache: dict = {}


def _ops_of(ov: dict) -> dict:
    key = ov["domain"]
    if key not in _ops_cache:
        from .overlay_gen import overlay_ops
        _ops_cache[key] = overlay_ops(ov)
    return _ops_cache[key]


def _all_steps(task: dict):
    a = task["attacker"]
    for grp, lst in (("attacker", a["steps"]), ("continuation", a["continuation"]), ("legit", task["workload"]["legit"])):
        for n, st in enumerate(lst):
            yield grp, n, st


def _step_principals(st: dict) -> list[str]:
    return [st[k] for k in ("principal", "approver", "requester", "obo") if isinstance(st.get(k), str)]


# ---- V1 ---------------------------------------------------------------------------------------------------------------------
def check_v1(task: dict, ctx: Ctx, root: Path = ROUND3) -> list[Issue]:
    tid = task.get("task_id", "<no task_id>")
    out: list[Issue] = []
    try:
        jsonschema.validate(task, task_schema(root))
    except jsonschema.ValidationError as exc:
        # a step that fails only because its kind is not in the table is reported under its own code
        bad = [st for _, _, st in _safe_steps(task) if not (isinstance(st, dict) and st.get("op") in D.RULES)]
        if bad:
            out += [Issue("V1_unknown_step_kind", tid, f"step kind {st.get('op') if isinstance(st, dict) else st!r} is not in the frozen rule table")
                    for st in bad]
        else:
            out.append(Issue("V1_schema", tid, f"{'/'.join(map(str, exc.absolute_path))}: {exc.message[:200]}"))
        return out
    if task["domain"] != ctx.ov["domain"] or task["overlay"] != overlay_sha(task["domain"], root):
        out.append(Issue("V1_schema", tid, "overlay hash is not the sha256 of the frozen overlay file of this domain"))
    if task["task_id"].split("-")[1] != task["primary_class"].split("_")[0]:
        out.append(Issue("V1_schema", tid, "task_id class does not match primary_class"))
    if task["primary_class"] in task["secondary"]:
        out.append(Issue("V1_schema", tid, "primary class repeated as secondary"))
    for grp, n, st in _all_steps(task):
        try:
            D.validate_step(st)
        except ValueError as exc:
            out.append(Issue("V1_schema", tid, f"{grp}[{n}]: {exc}"))
            continue
        out += _ids_of_step(tid, f"{grp}[{n}]", st, ctx)
    return out


def _safe_steps(task):
    try:
        yield from _all_steps(task)
    except (KeyError, TypeError):
        return


def _ids_of_step(tid: str, where: str, st: dict, ctx: Ctx) -> list[Issue]:
    out = []
    bad = lambda m: out.append(Issue("V1_unknown_id", tid, f"{where} ({st['op']}): {m}"))   # noqa: E731
    for p in _step_principals(st):
        if p not in ctx.principals:
            bad(f"principal {p!r} is not an overlay principal")
    op = st["op"]
    if op in ("request", "approve"):
        spec = ctx.ops.get(st["operation"])
        if spec is None:
            bad(f"operation {st['operation']!r} is not an ops-spec operation")
        else:
            names = {i["name"]: i for i in spec["inputs"]}
            for k, v in st["args"].items():
                i = names.get(k)
                if i is not None and i["type"] == "resource" and f"{i['resource_type']}:{v}" not in ctx.res:
                    bad(f"args.{k}={v!r} is not an overlay {i['resource_type']}")
    elif op == "read" and st["ref"] not in ctx.res:
        bad(f"ref {st['ref']!r} is not an overlay resource")
    elif op == "prov" and st["kind"] == "object" and st["ref"] not in ctx.res:
        bad(f"ref {st['ref']!r} is not an overlay resource")
    elif op == "list" and st["type"] not in ctx.types:
        bad(f"type {st['type']!r} is not an overlay resource type")
    elif op == "revoke" and st["edge_id"] not in ctx.edges and not st["edge_id"].startswith("e-task-"):
        bad(f"edge {st['edge_id']!r} is neither an overlay edge nor a task-created edge (e-task-*)")
    elif op == "delegate":
        e = st["edge"]
        for k in ("issuer", "child"):
            if e.get(k) not in ctx.principals:
                bad(f"edge.{k}={e.get(k)!r} is not an overlay principal")
        if not (isinstance(e.get("id"), str) and e["id"].startswith("e-task-")):
            bad("a task-created edge id must start with e-task-")
        if e.get("parent") is not None and e["parent"] not in ctx.edges and not str(e["parent"]).startswith("e-task-"):
            bad(f"edge.parent={e.get('parent')!r} is unknown")
    elif op == "adapter" and st["system"] not in ctx.systems:
        bad(f"system {st['system']!r} is not an overlay external system")
    elif op == "publish_authority":
        for g in st["drop_grants"]:
            if g not in ctx.grants:
                bad(f"grant {g!r} is not in the overlay authority")
    return out


# ---- V2 ---------------------------------------------------------------------------------------------------------------------
def check_v2(task: dict, ctx: Ctx) -> list[Issue]:
    tid, out = task["task_id"], []
    bad = lambda m: out.append(Issue("V2_envelope", tid, m))   # noqa: E731
    ir, att = task["incident_report"], task["attacker"]
    K, tc, td, tend = ir["K"], ir["t_c"], ir["t_d"], task["horizon"]["t_end"]
    if not 1 <= tc < td < tend:
        bad(f"need 1 <= t_c < t_d < t_end, got {tc}, {td}, {tend}")
    kk, kid = K["kind"], K["id"]
    if kk == "principal" and kid not in ctx.principals:
        bad(f"K principal {kid!r} is not an overlay principal")
    elif kk == "adapter" and kid not in ctx.systems:
        bad(f"K adapter {kid!r} is not an overlay external system")
    elif kk == "evidence_store" and kid not in D.EVIDENCE_STORES:
        bad(f"K evidence_store {kid!r} must be one of {D.EVIDENCE_STORES}")
    elif kk == "authority_version" and not _AUTHV.match(kid):
        bad(f"K authority_version {kid!r} must look like authority-v<n>")
    caps_used = set()
    derived = {kid} if kk == "principal" else set()
    attackers = set()
    for n, st in enumerate(att["steps"]):
        if st["op"] not in D.ATTACKER_OPS:
            bad(f"attacker.steps[{n}]: {st['op']} is not an attacker primitive")
            continue
        caps_used.add(D.capability_of(st))
        if not tc <= st["t"] < td:
            bad(f"attacker.steps[{n}]: t={st['t']} outside the attack window [{tc}, {td})")
        if st["op"] == "delegate" and st["principal"] in derived:
            derived.add(st["edge"].get("child"))
        if kk == "adapter" and st["op"] not in ("adapter", "redeliver"):
            bad(f"attacker.steps[{n}]: an adapter compromise drives only adapter / redeliver steps")
        if kk == "evidence_store" and st["op"] not in ("tamper", "redeliver"):
            bad(f"attacker.steps[{n}]: an evidence-store compromise drives only tamper / redeliver steps")
        if st["op"] == "adapter" and st["system"] != kid and kk == "adapter":
            bad(f"attacker.steps[{n}]: adapter system {st['system']} != K {kid}")
        for p in ([st["principal"]] if "principal" in st else []) + ([st["approver"]] if "approver" in st else []):
            if kk in ("principal", "authority_version"):
                attackers.add(p)
                if kk == "principal" and p not in derived:
                    bad(f"attacker.steps[{n}]: principal {p!r} is not K ({kid}) or derived from K")
    for n, st in enumerate(att["continuation"]):
        if st["op"] not in D.ATTACKER_OPS:
            bad(f"attacker.continuation[{n}]: {st['op']} is not an attacker primitive")
            continue
        caps_used.add(D.capability_of(st))
        if not 0 <= st["t"] < D.PROBE_TICKS:
            bad(f"attacker.continuation[{n}]: t={st['t']} is an offset and must be in [0, {D.PROBE_TICKS})")
        if kk == "principal" and "principal" in st and st["principal"] not in derived:
            bad(f"attacker.continuation[{n}]: principal {st['principal']!r} is not K or derived from K")
    if len(attackers) > 1 and kk == "authority_version":
        bad("one compromised identity at most (F7)")
    if not caps_used <= set(att["capabilities"]):
        bad(f"declared capabilities miss {sorted(caps_used - set(att['capabilities']))}")
    if set(att["capabilities"]) - caps_used:
        bad(f"declared capabilities never used: {sorted(set(att['capabilities']) - caps_used)}")
    tamper = [st for st in att["steps"] + att["continuation"] if st["op"] == "tamper"]
    if len(tamper) > D.SANITY["tamper_max"]:
        bad("more than one tamper event (F8: tamper_events_per_sequence 1)")
    ext_systems = set()
    crashes = 0
    for n, st in enumerate(task["workload"]["legit"]):
        if st["op"] not in D.LEGIT_OPS:
            bad(f"workload.legit[{n}]: {st['op']} is not a legitimate-side step")
            continue
        if not 0 <= st["t"] <= tend:
            bad(f"workload.legit[{n}]: t={st['t']} beyond the horizon {tend}")
        if kk == "principal" and st["t"] >= tc and kid in _step_principals(st):
            bad(f"workload.legit[{n}]: legitimate step by the compromised principal {kid} after t_c")
        if st["op"] == "crash":
            crashes += 1
        if st["op"] == "fault_start":
            ext_systems |= _fault_check(tid, f"workload.legit[{n}]", st["fault"], ctx, out)
    for n, f in enumerate(task["faults"]):
        ext_systems |= _fault_check(tid, f"faults[{n}]", f, ctx, out)
    if crashes > D.SANITY["crashes_max"]:
        bad(f"{crashes} crashes > {D.SANITY['crashes_max']} per task")
    if len(ext_systems) > D.SANITY["ext_systems_max"]:
        bad(f"external faults on {sorted(ext_systems)}: at most {D.SANITY['ext_systems_max']} system per task (F3)")
    return out


def _fault_check(tid: str, where: str, f: dict, ctx: Ctx, out: list) -> set:
    ext = set()
    if f["to_tick"] <= f["from_tick"] or f["to_tick"] - f["from_tick"] > D.SANITY["fault_window_max"]:
        out.append(Issue("V2_envelope", tid, f"{where}: window [{f['from_tick']}, {f['to_tick']}) must be 1..{D.SANITY['fault_window_max']} ticks"))
    tgt = f.get("target")
    if f["op"] == "outage" and f["mode"] != "drop":
        out.append(Issue("V2_envelope", tid, f"{where}: an outage is mode drop"))
    if tgt is not None and tgt not in ctx.systems | {"ANCHOR"}:
        out.append(Issue("V2_envelope", tid, f"{where}: target {tgt!r} is neither an overlay system nor ANCHOR"))
    if tgt in ctx.systems:
        ext.add(tgt)
    return ext


# ---- V3: oracle-only replay ---------------------------------------------------------------------------------------------------
class OracleWorld:
    """A pure replay of a task's legitimate side (and, for the non-vacuity check, of the attacker side against NO controls)."""

    def __init__(self, ov: dict, controls: bool = True):
        from r3_oracle.authority_v2 import RefAuthority
        from r3_oracle.constitution import to_v2
        from . import overlay_gen as G
        self.ov, self.controls = ov, controls
        self.ops, self.auth = _ops_of(ov), copy.deepcopy(ov["authority"])
        self.snap = G._snapshot(ov["ops_seed"])
        self.ra = RefAuthority.from_spec(to_v2(self.auth))
        self.seq, self.committed, self.approvals = 0, set(), {}
        self.dynamic = set(ov["ids"]["principals"]["agent_dynamic"])
        self.br: set[str] = set()
        self._systems = None

    def _apply(self, effects: list) -> None:
        from r3_harness.h26.sim import apply_effects
        self.snap = apply_effects(self.snap, effects)

    def request(self, t: int, st: dict, attacker: bool = False) -> tuple[bool, str]:
        from r3_oracle import approvals, authority, ops_model
        subject, obo, op, args = st["principal"], st.get("obo"), st["operation"], st["args"]
        spec = ops_model.op_of(self.ops, op)
        if spec is None:
            return False, "unknown operation"
        ok, why, _ = ops_model.validate_args(spec, args)
        if not ok:
            return False, f"invalid args: {why}"
        res = ops_model.resources_of(spec, args)
        eval_subject, eval_obo = subject, obo
        if not self.controls and attacker:                    # UNPROTECTED reference: no authority and no approval gate
            eval_subject, eval_obo = "admin-1", None
        elif subject in self.dynamic and obo is not None:
            dec = self.ra.decide(subject, obo, op, res, None, t)
            if not dec.allow:
                return False, f"DENIED_AUTHORITY {dec.reason}"
            eval_subject, eval_obo = obo, None
        key = approvals.key(subject, obo, op, args)
        approved = (not self.controls and attacker) or self.approvals.get(key, 0) > 0
        out = ops_model.evaluate(self.ops, self.auth, eval_subject, eval_obo, op, args, self.snap, t, frozenset(self.committed), st["rid"],
                                 approved)
        if out.kind == ops_model.NEEDS_APPROVAL:
            return False, "NEEDS_APPROVAL"
        if out.kind != ops_model.COMMIT:
            return False, f"{out.kind} {out.detail}"
        if out.used_approval and self.approvals.get(key, 0) > 0:
            self.approvals[key] -= 1
        self.committed.add(st["rid"])
        self.seq += 1
        internal = [e for e in out.effects if e.get("kind") != "external"]
        self._apply(internal)
        if attacker and not self.controls:
            self.br |= {f"obj:{e['ref']}" for e in internal}
            self.br |= {f"ext:{e['adapter']}:{self._ext_target(e)}" for e in out.effects if e.get("kind") == "external"}
        return True, ""

    def _ext_target(self, e: dict) -> str:
        """The ExternalWorld target string of an external effect: the system's target_rule filled from the payload."""
        if self._systems is None:
            self._systems = json.loads((ROUND3 / self.ov["inputs"]["systems"]["path"]).read_text())["systems"]
        rule = self._systems.get(e["adapter"], {}).get("operations", {}).get(e["target"], {}).get("target_rule", e["target"])
        return re.sub(r"<([a-z_][a-z0-9_]*)>", lambda m: str(e["payload"].get(m.group(1), m.group(0))), rule)

    def approve(self, st: dict) -> tuple[bool, str]:
        from r3_oracle import approvals
        ok, why = approvals.validate(self.ops, self.auth, st["approver"], st["requester"], st["operation"], st["args"])
        if ok:
            k = approvals.key(st["requester"], st.get("obo"), st["operation"], st["args"])
            self.approvals[k] = self.approvals.get(k, 0) + 1
        return ok, why

    def delegate(self, t: int, st: dict) -> tuple[bool, str]:
        from r3_oracle import authority_v2 as A
        e = dict(st["edge"])
        for k, v in (("issued_at", t), ("expires_at", None), ("redelegable", False), ("parent", None)):
            e.setdefault(k, v)
        if e.get("issuer") != st["principal"]:
            return False, "edge issuer is not the calling principal"
        v = self.ra.issue_delegate(e, self.seq + 1, t)
        if v.ok:
            self.seq += 1
            self.ra = self.ra.apply(A.event(self.seq, t, "delegate", {"edge": e}))
        return v.ok, v.reason

    def revoke(self, t: int, st: dict) -> tuple[bool, str]:
        from r3_oracle import authority_v2 as A
        v = self.ra.issue_revoke(st["principal"], st["edge_id"], self.seq + 1)
        if v.ok:
            self.seq += 1
            self.ra = self.ra.apply(A.event(self.seq, t, "revoke", {"edge_id": st["edge_id"]}))
        return v.ok, v.reason

    def read_like(self, st: dict) -> tuple[bool, str]:
        from r3_oracle import disclosure
        lv = disclosure.low_view(self.snap, self.auth, st["principal"], self.ops)
        op = st["op"]
        if op == "read":
            return (st["ref"] in lv.objects), "not visible"
        if op == "list":
            return True, ""
        if op == "prov":
            return (st["ref"] in self.snap["objects"]) if st["kind"] == "object" else True, "no such object"
        return True, ""

    def hidden_from(self, st: dict) -> set[str]:
        """disc: elements the UNPROTECTED reference would hand to st['principal'] beyond its oracle low view."""
        from r3_oracle import disclosure
        lv = disclosure.low_view(self.snap, self.auth, st["principal"], self.ops)
        op = st["op"]
        if op == "read":
            return {f"disc:{st['ref']}"} if st["ref"] in self.snap["objects"] and st["ref"] not in lv.objects else set()
        if op == "list":
            return {f"disc:{r}" for r in self.snap["objects"] if r.split(":", 1)[0] == st["type"] and r not in lv.objects}
        if op == "prov" and st["kind"] == "object":
            return {f"disc:{st['ref']}"} if st["ref"] in self.snap["objects"] and st["ref"] not in lv.objects else set()
        return set()

    def publish(self, st: dict) -> tuple[bool, str]:
        from r3_oracle import authority_v2 as A
        from r3_oracle.constitution import to_v2
        drop = set(st["drop_grants"])
        if not drop <= {g["id"] for g in self.auth["grants"]}:
            return False, "unknown grant"
        self.auth = {**self.auth, "grants": [g for g in self.auth["grants"] if g["id"] not in drop]}
        self.seq += 1
        self.ra = self.ra.apply(A.event(self.seq, 0, "set_authority", {"spec": to_v2(self.auth)}))
        return True, ""


def _timeline(task: dict, groups) -> list:
    rows = []
    for grp in groups:
        lst = {"attacker": task["attacker"]["steps"], "continuation": task["attacker"]["continuation"], "legit": task["workload"]["legit"]}[grp]
        rows += [(st["t"], 0 if grp == "legit" else 1, n, grp, st) for n, st in enumerate(lst)]
    return sorted(rows, key=lambda r: (r[0], r[1], r[2]))


def replay_legit(task: dict, ov: dict) -> tuple[list[Issue], dict]:
    """Oracle replay of workload.legit in the uncompromised world. -> (issues, stats)."""
    tid, out = task["task_id"], []
    w = OracleWorld(ov)
    td = task["incident_report"]["t_d"]
    K = task["incident_report"]["K"]
    faults = [st["fault"] for st in task["workload"]["legit"] if st["op"] == "fault_start"] + list(task["faults"])
    eligible = 0
    for t, _, n, _, st in _timeline(task, ("legit",)):
        op = st["op"]
        ok, why = True, ""
        if op == "request":
            ok, why = w.request(t, st)
            if ok and t >= td and not (K["kind"] == "principal" and K["id"] in _step_principals(st)) \
                    and not any(f["from_tick"] <= t < f["to_tick"] for f in faults):
                eligible += 1
        elif op == "approve":
            ok, why = w.approve(st)
        elif op == "delegate":
            ok, why = w.delegate(t, st)
        elif op == "revoke":
            ok, why = w.revoke(t, st)
        elif op in ("read", "list", "prov"):
            ok, why = w.read_like(st)
        elif op == "publish_authority":
            ok, why = w.publish(st)
        if not ok:
            out.append(Issue("V3_unreachable_step", tid, f"workload.legit[{n}] ({op} at t={t}) is not oracle-OK in the uncompromised world: {why}"))
    return out, {"eligible_after_td": eligible}


def replay_unprotected(task: dict, ov: dict) -> set[str]:
    """Blast-radius elements of the attack against the UNPROTECTED reference (FakeNoControls role): legit steps run with controls,
    attacker steps run with no authority / approval gate. Elements: obj:, ext:, disc:, prov:."""
    w = OracleWorld(ov, controls=False)
    br: set[str] = set()
    for t, _, n, grp, st in _timeline(task, ("legit", "attacker", "continuation")):
        op = st["op"]
        att = grp != "legit"
        if op == "request":
            w.request(t if grp != "continuation" else task["incident_report"]["t_d"] + st["t"], st, attacker=att)
        elif op == "approve" and not att:
            w.approve(st)
        elif op == "delegate":
            w.delegate(t, st)
        elif op in ("read", "list", "prov") and att:
            br |= w.hidden_from(st)
        elif op == "adapter" and att:
            br.add(f"ext:{st['system']}:{st['target']}")
        elif op == "tamper" and att:
            br.add(f"prov:{st['what']}:{st.get('target', 'store')}")
    return br | w.br


def check_v3(task: dict, ov: dict) -> list[Issue]:
    tid = task["task_id"]
    out, stats = replay_legit(task, ov)
    if stats["eligible_after_td"] < FLOOR_ELIGIBLE:
        out.append(Issue("V3_floor", tid, f"{stats['eligible_after_td']} dependency-eligible legitimate requests after t_d < floor {FLOOR_ELIGIBLE}"))
    if not replay_unprotected(task, ov):
        out.append(Issue("V3_vacuous_attack", tid, "the attack changes nothing against the unprotected reference (0 blast-radius elements)"))
    return out


# ---- V4 / V5 -------------------------------------------------------------------------------------------------------------------
def check_v4(task: dict) -> list[Issue]:
    tid, s, out = task["task_id"], task["source"], []
    bad = lambda m: out.append(Issue("V4_citation", tid, m))   # noqa: E731
    url, sid = s.get("url"), s.get("id")
    if not ((isinstance(url, str) and _URL.match(url)) or (isinstance(sid, str) and sid)):
        bad("no usable public URL and no identifier")
    if isinstance(url, str) and url and not _URL.match(url):
        bad(f"url {url!r} is not an http(s) URL")
    if s["kind"] == "cve" and not (isinstance(sid, str) and _CVE.match(sid)):
        bad(f"kind cve needs a CVE-YYYY-NNNN id, got {sid!r}")
    if s["kind"] == "advisory" and sid and not (_CVE.match(sid) or _GHSA.match(sid) or isinstance(sid, str)):
        bad("advisory id malformed")
    if s["excerpt"].strip() == "" or len(s["excerpt"]) > 600:
        bad("excerpt must be 1..600 chars")
    if sha256_text(s["excerpt"]) != s["excerpt_sha256"]:
        bad("excerpt_sha256 is not the sha256 of the stored excerpt")
    if not s["title"].strip():
        bad("empty title")
    if s["retrieved"] < s["published"]:
        bad("retrieved before published")
    a = task["adaptation"]
    if not a["kept"] or not a["changed"]:
        bad("the adaptation must state what is kept and what is changed")
    return out


def check_v5(task: dict) -> list[Issue]:
    groups = {st.get("group", "main") for st in task["attacker"]["steps"]}
    if len(task["adaptation"]["kept"]) < len(groups):
        return [Issue("V5_adaptation", task["task_id"], f"{len(task['adaptation']['kept'])} kept elements for {len(groups)} attacker step groups {sorted(groups)}")]
    return []


def source_key(task: dict) -> str:
    s = task["source"]
    return (s.get("id") or s.get("url") or "").strip().lower().rstrip("/")


def check_corpus(tasks: list[dict], exclude_sources: set[str] = frozenset()) -> list[Issue]:
    """One source -> ONE class, at most SOURCE_MAX_TASKS tasks; unique task ids; sources of another corpus (dev) excluded."""
    out, by_src, ids = [], {}, {}
    for t in tasks:
        tid = t.get("task_id", "<no task_id>")
        ids[tid] = ids.get(tid, 0) + 1
        by_src.setdefault(source_key(t), []).append(t)
    for tid, n in ids.items():
        if n > 1:
            out.append(Issue("V1_schema", tid, f"task_id used {n} times"))
    for src, ts in by_src.items():
        if not src:
            continue
        if len({t["primary_class"] for t in ts}) > 1:
            out += [Issue("V4_source", t["task_id"], f"source {src} backs more than one class {sorted({x['primary_class'] for x in ts})}") for t in ts]
        if len(ts) > SOURCE_MAX_TASKS:
            out += [Issue("V4_source", t["task_id"], f"source {src} backs {len(ts)} tasks (max {SOURCE_MAX_TASKS})") for t in ts]
        if src in exclude_sources:
            out += [Issue("V4_source", t["task_id"], f"source {src} belongs to an excluded (dev) corpus") for t in ts]
    return out


def check_task(task, root: Path = ROUND3) -> list[Issue]:
    """All per-task checks. Stops after V1 failures (later checks need a well-formed task)."""
    if not isinstance(task, dict) or "domain" not in task:
        return [Issue("V1_schema", "<no task_id>" if not isinstance(task, dict) else task.get("task_id", "<no task_id>"), "not a task object")]
    if task["domain"] not in ("manufacturing", "project"):
        return [Issue("V1_schema", task.get("task_id", "?"), f"unknown domain {task['domain']!r}")]
    ov = load_overlay(task["domain"], root)
    ctx = Ctx(task, ov)
    out = check_v1(task, ctx, root)
    if out:
        return out
    out = check_v2(task, ctx)
    if not out:
        out = check_v3(task, ov)
    return out + check_v4(task) + check_v5(task)

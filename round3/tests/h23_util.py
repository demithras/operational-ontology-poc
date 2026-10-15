"""Hand-built worlds for oracle unit tests."""
from r3_oracle.view import View


def snap(objs: dict, links=()):
    return {"objects": {k: {"props": dict(v), "version": 1} for k, v in objs.items()},
            "links": [list(x) for x in links], "effects": []}


def view(objs: dict, links=(), now=0, relations=(), config=None):
    return View(snap(objs, links), now, relations, config)

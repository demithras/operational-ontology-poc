"""File-only baseline for H18: Git + JSON files + JSON Schema + Python CI scripts, no semantic runtime.

State = the same canonical artifact files (ontology/objects, ontology/links). A 'change' is an edit of those files;
``ci.check(before, after)`` is the CI gate that accepts or rejects it. Shared plumbing (repo.py, ci.py, derive.py) is
the baseline's recurring complexity; rules/actions/queries/replication are the per-task bespoke surface.
"""

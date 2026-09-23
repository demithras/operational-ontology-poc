"""Shared code for the fake source-system services (erp/mes/wms).

This package holds only generic plumbing (connection pooling, fault
injection scaffolding) — never any cross-system data access. Each service
still connects with its own, separately-credentialed database role; nothing
here lets one system read or write another's tables
(docs/experiment/spec/02_scope_and_non_goals.md: "the ontology layer cannot
cheat with cross-database SQL" — the same boundary applies to these fake
sources themselves).
"""

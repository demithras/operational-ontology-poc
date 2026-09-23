"""Fake ERP source system (docs/experiment/spec/02_scope_and_non_goals.md).

Owns: suppliers, parts, purchase orders + lines. ERP-local part ids look
like PART-xxxxx; ERP has no knowledge of MES/WMS local identifiers or of
canonical ontology ids — that alignment happens in Phase 3's identity
resolver, not here.
"""

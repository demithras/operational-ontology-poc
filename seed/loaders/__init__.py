"""Per-system seed loaders, called by seed/load.py. Each module connects
only to its own system's database using that system's own credentials
(no cross-database access) — the same ownership boundary the fake source
services themselves enforce."""

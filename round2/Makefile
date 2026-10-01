.PHONY: check test freeze

check:
	python scripts/check_pack.py

test:
	python -m pytest -q

freeze: check test
	python scripts/freeze_protocol.py

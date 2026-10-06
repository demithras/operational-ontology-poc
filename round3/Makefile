.PHONY: check freeze index test

check:
	python scripts/check_pack.py

freeze: check
	python scripts/freeze_protocol.py

index:
	python scripts/build_file_index.py

test:
	.venv/bin/python -m pytest -q

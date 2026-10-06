PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
.PHONY: check freeze index test

check:
	$(PY) scripts/check_pack.py

freeze: check
	$(PY) scripts/freeze_protocol.py

index:
	$(PY) scripts/build_file_index.py

test:
	$(PY) -m pytest -q

PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
.PHONY: check freeze freeze-thresholds index

check:
	$(PY) scripts/check_pack.py

freeze: check
	$(PY) scripts/freeze_protocol.py --stage pack

freeze-thresholds: check
	$(PY) scripts/freeze_protocol.py --stage thresholds

index:
	$(PY) scripts/build_file_index.py

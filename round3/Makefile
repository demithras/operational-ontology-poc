.PHONY: check freeze index

check:
	python scripts/check_pack.py

freeze: check
	python scripts/freeze_protocol.py

index:
	python scripts/build_file_index.py

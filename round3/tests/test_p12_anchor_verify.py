"""P12: verify_anchor_log must report malformed lines as a failed verification, never raise."""
import json

import pytest

from r3_shared.anchor import LOG_NAME, verify_anchor_log


@pytest.mark.parametrize("line", ["{}", '{"seq": "x"}', '{"seq": true}', "[]", "3", "null",
                                  '{"seq": 1, "stream": ["a"]}', '{"seq": 1.5}'])
def test_malformed_line_is_a_failed_verification_not_an_exception(tmp_path, line):
    (tmp_path / LOG_NAME).write_text(line + "\n")
    v = verify_anchor_log(tmp_path, key=b"k" * 32)
    assert v["ok"] is False and any(e.startswith("line 0") for e in v["errors"])


def test_empty_object_among_good_shaped_lines_reports_that_line(tmp_path):
    (tmp_path / LOG_NAME).write_text(json.dumps({"i": 0}) + "\n{}\n")
    v = verify_anchor_log(tmp_path, key=b"k" * 32)
    assert v["ok"] is False and any(e.startswith("line 1") for e in v["errors"])

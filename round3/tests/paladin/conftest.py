import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from paladin_rig import Rig  # noqa: E402


@pytest.fixture
def mfg(tmp_path):
    return Rig(tmp_path, "manufacturing")


@pytest.fixture
def proj(tmp_path):
    return Rig(tmp_path, "project")


@pytest.fixture
def make_rig(tmp_path):
    def make(domain, **kw):
        return Rig(tmp_path, domain, **kw)
    return make

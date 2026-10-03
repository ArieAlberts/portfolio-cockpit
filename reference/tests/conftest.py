import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cockpit.config import load_config  # noqa: E402
from cockpit.repository import Repository  # noqa: E402
from cockpit import demo  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture
def repo():
    return Repository(":memory:")


@pytest.fixture
def seeded(repo):
    demo.seed_baseline(repo)
    return repo

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def posts():
    return json.loads((ROOT / "samples/posts.json").read_text())


@pytest.fixture
def boards():
    return json.loads((ROOT / "samples/boards.json").read_text())


@pytest.fixture
def events():
    folder = ROOT / "samples/events"
    return {p.name: json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))}

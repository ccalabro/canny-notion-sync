import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_demo_exits_zero_and_shows_unchanged():
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "sync.py"), "demo", "--page-size", "10"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert "20 created" in out or "created" in out
    assert "0 created, 0 updated, 20 unchanged" in out
    assert "post.status_changed" in out
    assert "wrong secret: HTTP 401" in out
    assert "10 minute old timestamp: HTTP 401" in out

"""Draw every panel view in headless Chromium with a mocked Home Assistant (skipped without playwright)."""
import json
import pathlib
import subprocess
import sys

import pytest

pytest.importorskip("playwright.sync_api")


def test_every_view_renders():
    out = subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("panel_smoke.py"))], capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert not result["crashed"], result
    assert not result["errors"], result

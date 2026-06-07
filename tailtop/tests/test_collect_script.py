"""The collect script must be valid POSIX sh. (Live output is captured into
fixtures and exercised by test_vitals.py — this only guards syntax so a broken
edit fails fast in CI without a Pi.)"""
from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "agent" / "fleet_collect.sh"


def test_script_exists() -> None:
    assert SCRIPT.is_file()


def test_script_is_valid_posix_sh() -> None:
    r = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

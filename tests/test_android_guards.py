"""Guards for the Android app's Roblox sign-in handling.

Everything runs in one process and pyjnius can call any Java method, so access modifiers don't stop the
Python side from accepting trades or reading the stored cookie. What keeps it from happening is that no
Python code asks: these tests fail if any of it ever does.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_FILES = sorted(p for d in ("android", "roliposter") for p in (ROOT / d).rglob("*.py")
                      if ".buildozer" not in p.parts and ".devdata" not in p.parts)


def _source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in PYTHON_FILES)


def test_python_files_found():
    assert any(p.name == "droid.py" for p in PYTHON_FILES)


def test_python_never_accepts_trades():
    assert not re.search(r"\.accept\s*\(", _source()), "only org.roliposter.AutoAccept may accept a trade"


def test_python_never_reads_the_roblox_sign_in():
    src = _source()
    assert not re.search(r"RobloxSession[^\n]*\.get\s*\(", src)
    # Reading cookies is fine for Rolimons (its sign-in), never for Roblox.
    assert not re.search(r"getCookie\([^)]*roblox", src, re.I)


def test_python_only_uses_the_allowed_roblox_requests():
    kinds = set(re.findall(r'RobloxDirect\.fetch\(\s*"([a-z]+)"', _source()))
    assert kinds <= {"list", "trade"}, kinds

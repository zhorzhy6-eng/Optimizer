"""Тесты системных вызовов (src/core/system/windows.py)."""
from __future__ import annotations

import os

from src.core.system import windows as system


def test_is_windows_matches_platform():
    assert system.is_windows() == (os.name == "nt")


def test_is_admin_returns_bool():
    result = system.is_admin()
    assert isinstance(result, bool)


def test_idle_seconds_non_negative():
    seconds = system.idle_seconds()
    assert isinstance(seconds, float)
    assert seconds >= 0.0


def test_codepage_oem_and_ansi():
    oem = system.codepage("oem")
    ansi = system.codepage("ansi")
    if os.name == "nt":
        assert isinstance(oem, int) and oem > 0
        assert isinstance(ansi, int) and ansi > 0
    else:
        assert oem is None and ansi is None


def test_codepage_default_is_oem():
    assert system.codepage() == system.codepage("oem")


def test_shell_uses_system_codepage():
    """shell берёт кодовую страницу из системного модуля, а не своей ctypes-логикой."""
    from src.core.system import shell

    encodings = shell.candidate_encodings()
    oem = system.codepage("oem")
    if oem:
        assert f"cp{oem}" in encodings

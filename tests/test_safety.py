"""Тесты общих правил безопасности (src/core/system/safety.py)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.system import safety


def test_normalize_is_absolute_and_case_insensitive():
    first = safety.normalize("C:\\Windows\\Temp")
    second = safety.normalize("c:/windows/temp/")
    assert first == second
    assert first.endswith("temp")


def test_drive_root_is_protected():
    if os.name != "nt":
        pytest.skip("проверка путей Windows")
    assert safety.is_protected(Path("C:\\")) is True


def test_system_and_profile_paths_are_protected():
    if os.name != "nt":
        pytest.skip("проверка путей Windows")
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    assert safety.is_protected(Path(system_root)) is True
    home = os.environ.get("USERPROFILE")
    if home:
        assert safety.is_protected(Path(home)) is True
        assert safety.is_protected(Path(home).parent) is True  # C:\Users


def test_temp_and_ordinary_paths_allowed(tmp_path):
    assert safety.is_protected(tmp_path) is False
    temp = os.environ.get("TEMP")
    if temp and os.name == "nt":
        assert safety.is_protected(Path(temp)) is False


def test_is_within():
    root = str(Path(os.environ.get("TEMP", ".")) / "safety_root")
    child = str(Path(root) / "sub" / "file.txt")
    other = str(Path(os.environ.get("TEMP", ".")) / "other" / "file.txt")
    assert safety.is_within(child, [root]) is True
    assert safety.is_within(root, [root]) is True
    assert safety.is_within(other, [root]) is False


def test_filter_safe_paths_drops_missing_and_protected(tmp_path):
    protected = os.environ.get("SystemRoot", r"C:\Windows") if os.name == "nt" else str(tmp_path)
    paths = [str(tmp_path), str(tmp_path / "missing"), protected]
    result = safety.filter_safe_paths(paths)
    assert str(tmp_path) in result or protected == str(tmp_path)
    assert str(tmp_path / "missing") not in result


def test_resolve_under(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")
    assert safety.resolve_under(target, [str(tmp_path)]) == target
    assert safety.resolve_under(target, [str(tmp_path / "elsewhere")]) is None

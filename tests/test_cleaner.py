"""Тесты модуля очистки мусора."""
from __future__ import annotations

import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from src.optimization.cleaner import Cleaner
from src.core.config import Config


def _make_cleaner(tmp_path):
    cfg = Config()
    cfg.log_dir = str(tmp_path / "logs")
    return Cleaner(cfg)


# --------------------------------------------------------------------- #
# Временные файлы
# --------------------------------------------------------------------- #
def test_clean_temp_removes_files_and_dirs(tmp_path):
    target = tmp_path / "temp"
    target.mkdir()
    (target / "a.tmp").write_text("x")
    sub = target / "sub"
    sub.mkdir()
    (sub / "b.tmp").write_text("y")

    cleaner = _make_cleaner(tmp_path)
    files, dirs = cleaner.clean_temp([str(target)])

    assert files == 2
    assert dirs == 1
    assert not (target / "a.tmp").exists()
    assert not sub.exists()


def test_clean_temp_missing_dir_is_safe(tmp_path):
    cleaner = _make_cleaner(tmp_path)
    files, dirs = cleaner.clean_temp([str(tmp_path / "does_not_exist")])
    assert files == 0
    assert dirs == 0


def test_clean_temp_removes_readonly_file(tmp_path):
    target = tmp_path / "temp_ro"
    target.mkdir()
    ro = target / "ro.tmp"
    ro.write_text("x")
    os.chmod(ro, stat.S_IREAD)  # атрибут «только чтение»

    cleaner = _make_cleaner(tmp_path)
    files, _dirs = cleaner.clean_temp([str(target)])

    assert files == 1
    assert not ro.exists()


def test_clean_temp_skips_protected_dir(monkeypatch, tmp_path):
    """Каталог из защитного списка не очищается ни при каких условиях."""
    target = tmp_path / "protected"
    target.mkdir()
    keep = target / "important.txt"
    keep.write_text("keep")

    cleaner = _make_cleaner(tmp_path)
    monkeypatch.setattr(cleaner, "_is_protected", lambda path: True)

    files, dirs = cleaner.clean_temp([str(target)])

    assert (files, dirs) == (0, 0)
    assert keep.exists()


def test_clean_temp_does_not_follow_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")

    target = tmp_path / "temp_link"
    target.mkdir()
    link = target / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("символические ссылки недоступны")

    cleaner = _make_cleaner(tmp_path)
    cleaner.clean_temp([str(target)])

    assert (outside / "keep.txt").exists()  # содержимое цели не тронуто
    assert not link.exists()


def test_clean_temp_does_not_follow_junction(tmp_path):
    outside = tmp_path / "outside_j"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")

    target = tmp_path / "temp_j"
    target.mkdir()
    link = target / "jlink"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip("junction не создан (нет прав)")

    cleaner = _make_cleaner(tmp_path)
    cleaner.clean_temp([str(target)])

    assert (outside / "keep.txt").exists()  # содержимое цели не тронуто
    assert not link.exists()


# --------------------------------------------------------------------- #
# Защита опасных путей
# --------------------------------------------------------------------- #
def test_is_protected_drive_root(tmp_path):
    cleaner = _make_cleaner(tmp_path)
    assert cleaner._is_protected(Path("C:\\")) is True


def test_is_protected_system_dir(tmp_path):
    cleaner = _make_cleaner(tmp_path)
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    assert cleaner._is_protected(Path(system_root)) is True


def test_is_protected_profile_parent(tmp_path):
    """Родитель профиля (C:\\Users) тоже защищён."""
    cleaner = _make_cleaner(tmp_path)
    home = os.environ.get("USERPROFILE")
    if not home:
        pytest.skip("USERPROFILE не задан")
    assert cleaner._is_protected(Path(home).parent) is True


def test_temp_paths_are_not_protected(tmp_path):
    cleaner = _make_cleaner(tmp_path)
    for var in ("TEMP", "TMP"):
        value = os.environ.get(var)
        if value:
            assert cleaner._is_protected(Path(value)) is False
    # C:\Windows\Temp разрешён (это не сам C:\Windows)
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    assert cleaner._is_protected(Path(system_root) / "Temp") is False


def test_ordinary_temp_dir_is_not_protected(tmp_path):
    cleaner = _make_cleaner(tmp_path)
    assert cleaner._is_protected(tmp_path) is False


# --------------------------------------------------------------------- #
# Корзина
# --------------------------------------------------------------------- #
def test_empty_recycle_bin(monkeypatch, tmp_path):
    cleaner = _make_cleaner(tmp_path)

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("src.core.system.shell.subprocess.run", lambda *a, **k: FakeResult())
    assert cleaner.empty_recycle_bin() is True


def test_empty_recycle_bin_treats_empty_bin_as_success(monkeypatch, tmp_path):
    """Пустая корзина — не ошибка: команда завершается кодом 0."""
    cleaner = _make_cleaner(tmp_path)
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = "The Recycle Bin is empty."

    def fake_run(args, **kwargs):
        captured["args"] = args
        return FakeResult()

    monkeypatch.setattr("src.core.system.shell.subprocess.run", fake_run)

    assert cleaner.empty_recycle_bin() is True
    assert "exit 0" in " ".join(captured["args"])


def test_empty_recycle_bin_reports_failure(monkeypatch, tmp_path):
    cleaner = _make_cleaner(tmp_path)

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "Access denied"

    monkeypatch.setattr("src.core.system.shell.subprocess.run", lambda *a, **k: FakeResult())
    assert cleaner.empty_recycle_bin() is False


# --------------------------------------------------------------------- #
# Старые логи
# --------------------------------------------------------------------- #
def test_clean_old_logs(tmp_path):
    cleaner = _make_cleaner(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()

    old = logs / "app.log.1"
    old.write_text("old")
    old_time = time.time() - 10 * 86400
    os.utime(old, (old_time, old_time))

    current = logs / "app.log"
    current.write_text("current")

    fresh = logs / "app.log.2"
    fresh.write_text("fresh")
    fresh_time = time.time()
    os.utime(fresh, (fresh_time, fresh_time))

    removed = cleaner.clean_old_logs(str(logs), retention_days=7)

    assert removed == 1
    assert not old.exists()
    assert current.exists()  # текущий файл не трогаем
    assert fresh.exists()    # свежий не трогаем

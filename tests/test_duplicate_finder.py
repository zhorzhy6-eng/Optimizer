"""Тесты поиска дубликатов (src/duplicate_finder.py)."""
from __future__ import annotations

import os
import time

from src.core.config import Config
from src.advanced.duplicate_finder import DuplicateFinder


def _finder(tmp_path, **kwargs) -> DuplicateFinder:
    cfg = Config()
    cfg.log_dir = str(tmp_path / "logs")
    cfg.duplicates_enabled = True
    cfg.duplicates_scan_paths = [str(tmp_path / "data")]
    cfg.duplicates_min_size_mb = 0
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return DuplicateFinder(cfg)


def _make_files(tmp_path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    first = data / "first.bin"
    second = data / "second.bin"
    unique = data / "unique.bin"
    payload = 1024 * 1024  # 1 МБ, чтобы «освобождено МБ» было наглядным
    first.write_bytes(b"A" * payload)
    second.write_bytes(b"A" * payload)
    unique.write_bytes(b"B" * payload)
    # разное время изменения, чтобы определить «старейший»
    old = time.time() - 3600
    os.utime(first, (old, old))
    return first, second, unique


def test_run_disabled_by_config(tmp_path):
    finder = _finder(tmp_path, duplicates_enabled=False)
    report = finder.run()
    assert report == {"scanned": 0, "large_files": [], "duplicate_groups": 0,
                      "duplicate_files": 0, "deleted": [], "freed_mb": 0.0, "errors": []}


def test_finds_duplicates(tmp_path):
    first, second, unique = _make_files(tmp_path)
    report = _finder(tmp_path).run()

    assert report["scanned"] == 3
    assert report["duplicate_groups"] == 1
    assert report["duplicate_files"] == 1
    assert report["deleted"] == []          # удаление выключено
    assert first.exists() and second.exists() and unique.exists()


def test_large_files_sorted_by_size(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "small.bin").write_bytes(b"x" * 100)
    (data / "big.bin").write_bytes(b"y" * 20000)

    report = _finder(tmp_path).run()
    assert report["large_files"][0]["path"].endswith("big.bin")


def test_delete_duplicates_keeps_oldest(tmp_path):
    first, second, unique = _make_files(tmp_path)
    finder = _finder(tmp_path, duplicates_delete=True)
    report = finder.run()

    assert first.exists()             # самая старая копия осталась
    assert not second.exists()        # копия удалена
    assert unique.exists()
    assert report["deleted"] == [str(second)]
    assert report["freed_mb"] > 0.5


def test_delete_refuses_files_outside_roots(tmp_path):
    """Файл вне разрешённых каталогов не удаляется."""
    first, second, unique = _make_files(tmp_path)
    finder = _finder(tmp_path, duplicates_delete=True)
    files = finder._collect([str(tmp_path / "data")], 0, 100)
    groups = finder.find_duplicates(files)

    outcome = finder.delete_duplicates(groups, [str(tmp_path / "other")])
    assert outcome["deleted"] == []
    assert first.exists() and second.exists()


def test_protected_scan_paths_are_skipped(tmp_path):
    finder = _finder(tmp_path, duplicates_scan_paths=["C:\\Windows"])
    report = finder.run()
    assert report["scanned"] == 0


def test_max_files_limit(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    for index in range(10):
        (data / f"file{index}.bin").write_bytes(b"z" * 100)

    report = _finder(tmp_path, duplicates_max_files=3).run()
    assert report["scanned"] == 3

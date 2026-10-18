"""Тесты отчётов (src/core/reporting.py)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from src.core import reporting
from src.core.config import Config


def _touch(path: Path, age_seconds: float) -> None:
    moment = time.time() - age_seconds
    os.utime(path, (moment, moment))


def test_format_report_contains_sections():
    text = reporting.format_report({
        "cleaner": {"temp_files_removed": 3, "temp_dirs_removed": 1,
                    "recycle_bin_cleaned": True, "old_logs_removed": 2},
        "process_monitor": {"process_count": 10, "heavy_processes": [
            {"pid": 1, "name": "a.exe", "cpu": 80.0, "ram": 5.0}], "closed_processes": ["x.exe"]},
        "power": {"scheme_applied": "balanced"},
        "defrag": {"C:": {"media_type": "SSD", "reason": "пропущено"}},
        "drivers": {"installed": ["a.inf"], "updated": False},
    })
    for fragment in ("[Очистка]", "[Процессы]", "[Питание]", "[Дефрагментация]", "[Драйверы]",
                     "a.exe", "SSD", "balanced", "a.inf"):
        assert fragment in text


def test_format_report_tolerates_partial_data():
    text = reporting.format_report({})
    assert "[Очистка]" in text
    assert "0" in text


def test_write_report_creates_file(tmp_path):
    cfg = Config()
    cfg.report_dir = str(tmp_path)
    path = reporting.write_report(cfg, {"cleaner": {"temp_files_removed": 1}})

    assert path is not None and path.exists()
    assert path.read_text(encoding="utf-8").startswith("Отчёт")


def test_find_last_report_returns_newest(tmp_path):
    old = tmp_path / "report_20240101_120000.txt"
    old.write_text("old", encoding="utf-8")
    new = tmp_path / "report_20240601_180000.txt"
    new.write_text("new", encoding="utf-8")
    _touch(old, 3600)
    _touch(new, 10)

    assert reporting.find_last_report(tmp_path) == new
    assert reporting.find_last_report(tmp_path / "missing") is None


def test_print_last_report_outputs_and_handles_bom(tmp_path, capsys):
    report = tmp_path / "report_20240602_180000.txt"
    report.write_text("Отчёт с BOM", encoding="utf-8-sig")

    assert reporting.print_last_report(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Отчёт с BOM" in out
    assert "\ufeff" not in out


def test_print_last_report_without_files(tmp_path, capsys):
    assert reporting.print_last_report(tmp_path) == 1
    assert "не найдены" in capsys.readouterr().out.lower()


def test_safe_print_does_not_raise(capsys):
    reporting.safe_print("обычный текст")
    assert "обычный текст" in capsys.readouterr().out

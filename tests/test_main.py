"""Тесты точки входа: флаги --light/--report/--mode, догоняющий запуск."""
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

import pytest

import src.main as main_module
from src.core.config import Config


def _fake_config(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.log_dir = str(tmp_path / "logs")
    cfg.report_dir = str(tmp_path / "logs")
    cfg.generate_report = False
    cfg.catch_up_on_wake = False
    return cfg


def _touch(path: Path, age_seconds: float) -> None:
    moment = time.time() - age_seconds
    os.utime(path, (moment, moment))


def test_find_last_report_returns_newest(tmp_path):
    old = tmp_path / "report_20240101_120000.txt"
    old.write_text("old", encoding="utf-8")
    new = tmp_path / "report_20240601_180000.txt"
    new.write_text("new", encoding="utf-8")
    _touch(old, age_seconds=3600)
    _touch(new, age_seconds=10)

    assert main_module.find_last_report(tmp_path) == new


def test_find_last_report_empty_dir(tmp_path):
    assert main_module.find_last_report(tmp_path) is None
    assert main_module.find_last_report(tmp_path / "missing") is None


def test_print_last_report_without_files(tmp_path, capsys):
    assert main_module.print_last_report(tmp_path) == 1
    assert "не найдены" in capsys.readouterr().out.lower()


def test_print_last_report_outputs_content(tmp_path, capsys):
    report = tmp_path / "report_20240601_180000.txt"
    report.write_text("Содержимое отчёта", encoding="utf-8")

    assert main_module.print_last_report(tmp_path) == 0
    assert "Содержимое отчёта" in capsys.readouterr().out


def test_print_last_report_handles_bom(tmp_path, capsys):
    """Файл отчёта с BOM (например, сохранённый внешним редактором) читается."""
    report = tmp_path / "report_20240602_180000.txt"
    report.write_text("Отчёт с BOM", encoding="utf-8-sig")

    assert main_module.print_last_report(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Отчёт с BOM" in out
    assert "\ufeff" not in out


def test_run_light_tasks_uses_only_cleaner(monkeypatch, tmp_path):
    cfg = _fake_config(tmp_path)

    class FakeCleaner:
        def __init__(self, config):
            self.config = config

        def run_all(self):
            return {"temp_files_removed": 3, "temp_dirs_removed": 1}

    monkeypatch.setattr("src.optimization.cleaner.Cleaner", FakeCleaner)

    report = main_module.run_light_tasks(cfg)
    assert report["cleaner"]["temp_files_removed"] == 3


@pytest.fixture
def mocks(monkeypatch, tmp_path):
    """Изолирует main() от реальной конфигурации и логирования."""
    cfg = _fake_config(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr(main_module.Config, "from_yaml", classmethod(lambda cls, path: cfg))
    monkeypatch.setattr(main_module, "setup_logging", lambda **kwargs: None)
    monkeypatch.setattr(main_module, "run_light_tasks", lambda c: calls.append("light") or {"cleaner": {}})
    monkeypatch.setattr(main_module, "run_all_tasks", lambda c: calls.append("full") or {})
    monkeypatch.setattr(main_module, "run_optimization", lambda c, s: calls.append("opt") or {})
    return cfg, calls


def test_main_light_runs_only_cleaner(mocks):
    _cfg, calls = mocks
    assert main_module.main(["--light"]) == 0
    assert calls == ["light"]


def test_main_mode_light(mocks):
    _cfg, calls = mocks
    assert main_module.main(["--mode", "light"]) == 0
    assert calls == ["light"]


def test_main_mode_full(mocks):
    _cfg, calls = mocks
    assert main_module.main(["--mode", "full"]) == 0
    assert calls == ["opt"]


def test_main_once_with_mode_light_no_double_run(mocks):
    """--once --mode light выполняет только лёгкую чистку (не полный цикл)."""
    cfg, calls = mocks
    cfg.catch_up_on_wake = True
    assert main_module.main(["--once", "--mode", "light"]) == 0
    assert calls == ["light"]


def test_main_once_does_not_double_run(mocks):
    """--once выполняет ровно один полный цикл (без догоняющего запуска)."""
    cfg, calls = mocks
    cfg.catch_up_on_wake = True
    assert main_module.main(["--once"]) == 0
    assert calls == ["opt"]


def test_main_report_flag_skips_tasks(mocks):
    _cfg, calls = mocks
    assert main_module.main(["--report"]) == 1  # отчётов ещё нет
    assert calls == []


# --------------------------------------------------------------------- #
# Догоняющий запуск: режим определяется по пропущенному времени
# --------------------------------------------------------------------- #
def _sched_config():
    cfg = Config()
    cfg.light_times = ["12:00"]
    cfg.full_times = ["18:00"]
    return cfg


def test_missed_run_mode_light():
    cfg = _sched_config()
    now = dt.datetime(2026, 9, 25, 13, 0)  # после 12:00, до 18:00
    assert main_module._missed_run_mode(cfg, last_run=None, now=now) == "light"


def test_missed_run_mode_full():
    cfg = _sched_config()
    now = dt.datetime(2026, 9, 25, 19, 0)  # после 18:00
    assert main_module._missed_run_mode(cfg, last_run=None, now=now) == "full"


def test_missed_run_mode_none_when_recent_run():
    cfg = _sched_config()
    now = dt.datetime(2026, 9, 25, 19, 0)
    last_run = dt.datetime(2026, 9, 25, 18, 30)
    assert main_module._missed_run_mode(cfg, last_run=last_run, now=now) is None


def test_missed_run_mode_none_before_first_time():
    cfg = _sched_config()
    now = dt.datetime(2026, 9, 25, 9, 0)  # до 12:00
    assert main_module._missed_run_mode(cfg, last_run=None, now=now) is None


def test_missed_run_mode_backward_compat():
    """Старый формат (только schedule_times) -> режим full."""
    cfg = Config()
    now = dt.datetime(2026, 9, 25, 13, 0)
    assert main_module._missed_run_mode(cfg, last_run=None, now=now) == "full"


# --------------------------------------------------------------------- #
# Расширенные функции (extra_steps)
# --------------------------------------------------------------------- #
def test_extra_steps_default_config_only_safe_checks():
    """По умолчанию выполняются только безопасные (читающие) модули."""
    keys = [key for key, _title, _action in main_module.extra_steps(Config())]
    assert keys == ["startup", "disk_health", "thermal"]


def test_extra_steps_all_disabled():
    cfg = Config()
    cfg.startup_enabled = False
    cfg.disk_health_enabled = False
    cfg.thermal_enabled = False
    assert main_module.extra_steps(cfg) == []


def test_extra_steps_all_enabled_in_order():
    cfg = Config()
    cfg.startup_enabled = True
    cfg.services_enabled = True
    cfg.network_enabled = True
    cfg.disk_health_enabled = True
    cfg.duplicates_enabled = True
    cfg.winget_enabled = True
    cfg.thermal_enabled = True

    keys = [key for key, _title, _action in main_module.extra_steps(cfg)]
    assert keys == ["startup", "services", "network", "disk_health",
                    "duplicates", "winget", "thermal"]


def test_extra_steps_actions_are_callable():
    for key, title, action in main_module.extra_steps(Config()):
        assert callable(action), key
        assert isinstance(title, str) and title

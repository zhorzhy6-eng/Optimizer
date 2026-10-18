"""Тесты загрузки конфигурации."""
from __future__ import annotations

import pytest

from src.core.config import Config

yaml = pytest.importorskip("yaml")


def test_defaults_when_file_missing(tmp_path):
    cfg = Config.from_yaml(tmp_path / "nope.yaml")
    assert cfg.schedule_times == ["12:00", "18:00"]
    assert cfg.light_times == []
    assert cfg.full_times == []  # дефолт; fallback в main/all_times()
    assert cfg.all_times() == ["12:00", "18:00"]
    assert cfg.game_scheme == "high_performance"
    assert cfg.office_scheme == "balanced"
    assert cfg.idle_scheme == "power_saver"
    assert cfg.cpu_threshold_percent == 50.0
    assert cfg.log_retention_days == 7


def test_default_scheme_guids():
    cfg = Config()
    assert cfg.power_schemes["ultimate"] == "e9a42b02-d5df-448d-aa00-03f14749eb61"


def test_all_times_combines_light_and_full():
    cfg = Config()
    cfg.light_times = ["12:00"]
    cfg.full_times = ["18:00", "12:00"]
    assert cfg.all_times() == ["12:00", "18:00"]  # без дублей


def test_all_times_falls_back_to_schedule_times():
    cfg = Config()
    cfg.light_times = []
    cfg.full_times = []
    assert cfg.all_times() == ["12:00", "18:00"]


def test_effective_full_times_prefers_full():
    cfg = Config()
    cfg.light_times = ["12:00"]
    cfg.full_times = ["18:00"]
    assert cfg.effective_full_times() == ["18:00"]


def test_effective_full_times_empty_when_only_light():
    """Если задана только лёгкая чистка, полный цикл не планируется."""
    cfg = Config()
    cfg.light_times = ["12:00"]
    cfg.full_times = []
    assert cfg.effective_full_times() == []


def test_effective_full_times_backward_compat():
    """Старый формат: times -> полный цикл."""
    cfg = Config()
    cfg.light_times = []
    cfg.full_times = []
    assert cfg.effective_full_times() == ["12:00", "18:00"]


def test_load_full_yaml(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        """
schedule:
  light_times: ["09:00"]
  full_times: ["21:30"]
  catch_up_on_wake: false
cleaner:
  temp_paths: ["%TEMP%"]
  log_retention_days: 3
process_monitor:
  cpu_threshold_percent: 80.0
  ram_threshold_percent: 70.0
  idle_minutes: 5
  unwanted_processes: ["foo.exe"]
power:
  game_scheme: "ultimate"
  office_scheme: "power_saver"
  idle_scheme: "balanced"
  game_processes: ["game.exe"]
  office_processes: ["word.exe"]
  schemes:
    high_performance: "custom-guid"
defrag:
  drives: ["D:"]
drivers:
  driver_folder: "C:\\\\Drv"
  enable_driver_update: true
  update_tool: "uso"
logging:
  level: "DEBUG"
  generate_report: false
""",
        encoding="utf-8",
    )

    cfg = Config.from_yaml(path)

    assert cfg.light_times == ["09:00"]
    assert cfg.full_times == ["21:30"]
    assert cfg.schedule_times == ["12:00", "18:00"]  # times не задан -> дефолт
    assert cfg.catch_up_on_wake is False
    assert cfg.temp_paths == ["%TEMP%"]
    assert cfg.log_retention_days == 3
    assert cfg.cpu_threshold_percent == 80.0
    assert cfg.ram_threshold_percent == 70.0
    assert cfg.idle_minutes == 5
    assert cfg.unwanted_processes == ["foo.exe"]
    assert cfg.game_scheme == "ultimate"
    assert cfg.office_scheme == "power_saver"
    assert cfg.idle_scheme == "balanced"
    assert cfg.game_processes == ["game.exe"]
    assert cfg.office_processes == ["word.exe"]
    assert cfg.power_schemes["high_performance"] == "custom-guid"
    # неуказанные схемы остаются по умолчанию
    assert cfg.power_schemes["balanced"] == "381b4222-f694-41f0-9685-ff5bb260df2e"
    assert cfg.defrag_drives == ["D:"]
    assert cfg.driver_folder == "C:\\Drv"
    assert cfg.enable_driver_update is True
    assert cfg.driver_update_tool == "uso"
    assert cfg.log_level == "DEBUG"
    assert cfg.generate_report is False


def test_backward_compat_old_times(tmp_path):
    """Старый формат: только times -> все запуски full."""
    path = tmp_path / "settings.yaml"
    path.write_text(
        """
schedule:
  times: ["08:00", "20:00"]
""",
        encoding="utf-8",
    )
    cfg = Config.from_yaml(path)
    assert cfg.schedule_times == ["08:00", "20:00"]
    assert cfg.light_times == []
    assert cfg.full_times == ["08:00", "20:00"]


def test_broken_yaml_returns_defaults(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("schedule: [unbalanced", encoding="utf-8")
    cfg = Config.from_yaml(path)
    # не упало и вернуло дефолты
    assert cfg.schedule_times == ["12:00", "18:00"]


def test_bad_numeric_value_does_not_reset_other_settings(tmp_path):
    """Одна опечатка в числе не должна отбрасывать всю конфигурацию."""
    path = tmp_path / "settings.yaml"
    path.write_text(
        "schedule:\n"
        '  light_times: ["07:30"]\n'
        "process_monitor:\n"
        "  cpu_threshold_percent: not-a-number\n"
        "  idle_minutes: 5\n"
        "cleaner:\n"
        "  log_retention_days: 3\n",
        encoding="utf-8",
    )
    cfg = Config.from_yaml(path)

    assert cfg.cpu_threshold_percent == 50.0   # плохое значение -> дефолт
    assert cfg.idle_minutes == 5               # соседние настройки сохранены
    assert cfg.light_times == ["07:30"]
    assert cfg.log_retention_days == 3


def test_numeric_strings_are_accepted(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "process_monitor:\n"
        '  cpu_threshold_percent: "70"\n'
        '  ram_threshold_percent: "60.5"\n'
        '  idle_minutes: "5"\n',
        encoding="utf-8",
    )
    cfg = Config.from_yaml(path)
    assert cfg.cpu_threshold_percent == 70.0
    assert cfg.ram_threshold_percent == 60.5
    assert cfg.idle_minutes == 5

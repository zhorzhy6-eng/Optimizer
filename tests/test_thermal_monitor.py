"""Тесты монитора температуры и троттлинга (src/thermal_monitor.py)."""
from __future__ import annotations

import json

from src.core.config import Config
from src.advanced.thermal_monitor import ThermalMonitor


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _monitor(tmp_path, **kwargs) -> ThermalMonitor:
    cfg = Config()
    cfg.log_dir = str(tmp_path)
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return ThermalMonitor(cfg)


def test_temperatures_convert_from_decikelvin(monkeypatch, tmp_path):
    payload = json.dumps([{"InstanceName": "ACPI\\ThermalZone", "CurrentTemperature": 3182}])
    monkeypatch.setattr("src.advanced.thermal_monitor.shell.run", lambda *a, **k: FakeResult(stdout=payload))

    readings = _monitor(tmp_path).temperatures()
    assert len(readings) == 1
    assert round(readings[0]["celsius"]) == 45  # 318.2 K


def test_temperatures_ignore_unrealistic_values(monkeypatch, tmp_path):
    payload = json.dumps([{"InstanceName": "x", "CurrentTemperature": 5}])
    monkeypatch.setattr("src.advanced.thermal_monitor.shell.run", lambda *a, **k: FakeResult(stdout=payload))
    assert _monitor(tmp_path).temperatures() == []


def test_is_throttling(tmp_path):
    monitor = _monitor(tmp_path, thermal_min_clock_percent=60.0)
    assert monitor.is_throttling({"current_mhz": 800.0, "max_mhz": 3000.0}) is True
    assert monitor.is_throttling({"current_mhz": 2900.0, "max_mhz": 3000.0}) is False
    assert monitor.is_throttling({"current_mhz": 0.0, "max_mhz": 3000.0}) is False


def test_run_warns_about_high_temperature(monkeypatch, tmp_path):
    monitor = _monitor(tmp_path, thermal_max_temperature_c=80.0)
    monkeypatch.setattr(monitor, "temperatures", lambda: [{"sensor": "ACPI", "celsius": 91.0}])
    monkeypatch.setattr(monitor, "cpu_clock", lambda: {"current_mhz": 3000.0, "max_mhz": 3000.0})

    report = monitor.run()
    assert report["max_temperature"] == 91.0
    assert any("91.0" in warning for warning in report["warnings"])
    assert report["power_scheme"] == ""      # реакция выключена


def test_run_warns_about_throttling(monkeypatch, tmp_path):
    monitor = _monitor(tmp_path, thermal_min_clock_percent=60.0, thermal_max_temperature_c=100.0)
    monkeypatch.setattr(monitor, "temperatures", lambda: [])
    monkeypatch.setattr(monitor, "cpu_clock", lambda: {"current_mhz": 700.0, "max_mhz": 3200.0})

    report = monitor.run()
    assert report["throttling"] is True
    assert any("троттлинг" in warning.lower() for warning in report["warnings"])


def test_run_switches_power_scheme_when_allowed(monkeypatch, tmp_path):
    monitor = _monitor(tmp_path, thermal_max_temperature_c=70.0,
                       thermal_switch_to_power_saver=True)
    monkeypatch.setattr(monitor, "temperatures", lambda: [{"sensor": "ACPI", "celsius": 95.0}])
    monkeypatch.setattr(monitor, "cpu_clock", lambda: {"current_mhz": 3000.0, "max_mhz": 3000.0})
    monkeypatch.setattr(monitor, "_switch_to_power_saver", lambda: "power_saver")

    report = monitor.run()
    assert report["power_scheme"] == "power_saver"


def test_run_handles_errors(monkeypatch, tmp_path):
    monitor = _monitor(tmp_path)

    def boom():
        raise RuntimeError("нет датчиков")

    monkeypatch.setattr(monitor, "temperatures", boom)
    report = monitor.run()
    assert report["warnings"]
    assert report["throttling"] is False

"""Тесты модуля здоровья дисков (src/disk_health.py)."""
from __future__ import annotations

import json

from src.core.config import Config
from src.advanced.disk_health import DiskHealth


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _health(tmp_path, **kwargs) -> DiskHealth:
    cfg = Config()
    cfg.log_dir = str(tmp_path)
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return DiskHealth(cfg)


def test_physical_disks_parsing(monkeypatch, tmp_path):
    payload = json.dumps([
        {"FriendlyName": "Samsung SSD", "MediaType": "SSD", "HealthStatus": "Healthy",
         "OperationalStatus": "OK", "Size": 512110190592},
    ])
    monkeypatch.setattr("src.advanced.disk_health.shell.run", lambda *a, **k: FakeResult(stdout=payload))

    disks = _health(tmp_path).physical_disks()
    assert disks[0]["name"] == "Samsung SSD"
    assert disks[0]["media_type"] == "SSD"
    assert disks[0]["health"] == "Healthy"
    assert disks[0]["size_gb"] > 400


def test_volumes_parsing(monkeypatch, tmp_path):
    payload = json.dumps([
        {"DriveLetter": "C", "FileSystemLabel": "System", "Size": 500000000000,
         "SizeRemaining": 25000000000},
    ])
    monkeypatch.setattr("src.advanced.disk_health.shell.run", lambda *a, **k: FakeResult(stdout=payload))

    volumes = _health(tmp_path).volumes()
    assert volumes[0]["drive"] == "C:"
    assert volumes[0]["free_percent"] == 5.0


def test_run_reports_low_disk_space(monkeypatch, tmp_path):
    health = _health(tmp_path, disk_health_warn_free_percent=10.0)
    monkeypatch.setattr(health, "physical_disks", lambda: [
        {"name": "SSD", "media_type": "SSD", "health": "Healthy", "status": "OK", "size_gb": 500}])
    monkeypatch.setattr(health, "volumes", lambda: [
        {"drive": "C:", "label": "", "size_gb": 500, "free_gb": 20, "free_percent": 4.0}])

    report = health.run()
    assert report["disks"]
    assert any("C:" in warning for warning in report["warnings"])


def test_run_reports_unhealthy_disk(monkeypatch, tmp_path):
    health = _health(tmp_path)
    monkeypatch.setattr(health, "physical_disks", lambda: [
        {"name": "HDD", "media_type": "HDD", "health": "Warning", "status": "OK", "size_gb": 1000}])
    monkeypatch.setattr(health, "volumes", lambda: [])

    report = health.run()
    assert any("HDD" in warning for warning in report["warnings"])


def test_run_without_warnings(monkeypatch, tmp_path):
    health = _health(tmp_path)
    monkeypatch.setattr(health, "physical_disks", lambda: [
        {"name": "SSD", "media_type": "SSD", "health": "Healthy", "status": "OK", "size_gb": 500}])
    monkeypatch.setattr(health, "volumes", lambda: [
        {"drive": "C:", "label": "", "size_gb": 500, "free_gb": 300, "free_percent": 60.0}])

    report = health.run()
    assert report["warnings"] == []


def test_query_tolerates_broken_json(monkeypatch, tmp_path):
    monkeypatch.setattr("src.advanced.disk_health.shell.run", lambda *a, **k: FakeResult(stdout="{не json"))
    assert _health(tmp_path).physical_disks() == []

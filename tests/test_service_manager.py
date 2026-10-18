"""Тесты управления службами (src/service_manager.py)."""
from __future__ import annotations

import json

from src.core.config import Config
from src.advanced.service_manager import CRITICAL_SERVICES, ServiceManager


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _manager(tmp_path, **kwargs) -> ServiceManager:
    cfg = Config()
    cfg.log_dir = str(tmp_path)
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return ServiceManager(cfg)


def test_critical_services_are_protected():
    for name in ("rpcss", "dcomlaunch", "plugplay", "power", "winmgmt", "eventlog"):
        assert name in CRITICAL_SERVICES


def test_protected_includes_config_extra(tmp_path):
    manager = _manager(tmp_path, services_protected=["MyCustomService"])
    assert "mycustomservice" in manager._protected()
    assert "rpcss" in manager._protected()


def test_set_start_mode_refuses_protected_service(monkeypatch, tmp_path):
    manager = _manager(tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError("sc.exe не должен вызываться для защищённой службы")

    monkeypatch.setattr("src.advanced.service_manager.shell.run", fail)
    assert manager.set_start_mode("RpcSs") is False


def test_set_start_mode_changes_service_and_backs_up(monkeypatch, tmp_path):
    manager = _manager(tmp_path)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["sc.exe", "qc"]:
            return FakeResult(stdout="START_TYPE         : 2   AUTO_START\n")
        return FakeResult(returncode=0)

    monkeypatch.setattr("src.advanced.service_manager.shell.run", fake_run)

    assert manager.set_start_mode("DiagTrack") is True
    assert ["sc.exe", "config", "DiagTrack", "start=", "demand"] in calls

    backup = json.loads((tmp_path / "services_backup.json").read_text(encoding="utf-8"))
    assert backup["DiagTrack"]["start_mode"] == "2"


def test_set_start_mode_skips_already_manual(monkeypatch, tmp_path):
    manager = _manager(tmp_path)

    def fake_run(args, **kwargs):
        return FakeResult(stdout="START_TYPE         : 3   DEMAND_START\n")

    monkeypatch.setattr("src.advanced.service_manager.shell.run", fake_run)
    assert manager.set_start_mode("DiagTrack") is True
    assert not (tmp_path / "services_backup.json").exists()


def test_run_without_targets_only_analyzes(monkeypatch, tmp_path):
    manager = _manager(tmp_path, services_disable=[])
    monkeypatch.setattr(manager, "list_services", lambda: [
        {"name": "DiagTrack", "display_name": "x", "start_mode": "Auto", "state": "Running"}])

    def fail(*args, **kwargs):
        raise AssertionError("изменения не должны выполняться")

    monkeypatch.setattr(manager, "set_start_mode", fail)
    report = manager.run()
    assert report["total"] == 1
    assert report["changed"] == []


def test_run_skips_protected_even_if_listed(monkeypatch, tmp_path):
    manager = _manager(tmp_path, services_disable=["RpcSs", "DiagTrack"])
    monkeypatch.setattr(manager, "list_services", lambda: [
        {"name": "RpcSs", "display_name": "RPC", "start_mode": "Auto", "state": "Running"},
        {"name": "DiagTrack", "display_name": "Diag", "start_mode": "Auto", "state": "Running"},
    ])
    monkeypatch.setattr(manager, "set_start_mode", lambda name, mode="Manual": name == "DiagTrack")

    report = manager.run()
    assert report["changed"] == ["DiagTrack"]
    assert report["skipped_protected"] == ["RpcSs"]


def test_list_services_parses_json(monkeypatch, tmp_path):
    manager = _manager(tmp_path)

    class JsonResult:
        returncode = 0
        stdout = '[{"Name":"DiagTrack","DisplayName":"Connected User Experiences",' \
                 '"StartMode":"Auto","State":"Running"}]'
        stderr = ""

    monkeypatch.setattr("src.advanced.service_manager.shell.run", lambda *a, **k: JsonResult())
    services = manager.list_services()
    assert services == [{"name": "DiagTrack", "display_name": "Connected User Experiences",
                         "start_mode": "Auto", "state": "Running"}]


def test_restore_services(monkeypatch, tmp_path):
    manager = _manager(tmp_path)
    (tmp_path / "services_backup.json").write_text(
        json.dumps({"DiagTrack": {"start_mode": "2"}}), encoding="utf-8")

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return FakeResult(returncode=0)

    monkeypatch.setattr("src.advanced.service_manager.shell.run", fake_run)
    restored = manager.restore_services()

    assert restored == ["DiagTrack"]
    assert ["sc.exe", "config", "DiagTrack", "start=", "auto"] in calls
    remaining = json.loads((tmp_path / "services_backup.json").read_text(encoding="utf-8"))
    assert remaining == {}

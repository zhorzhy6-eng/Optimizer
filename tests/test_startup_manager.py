"""Тесты модуля автозагрузки (src/startup_manager.py)."""
from __future__ import annotations

from pathlib import Path

import src.advanced.startup_manager as sm_module
from src.core.config import Config
from src.advanced.startup_manager import StartupManager


def _manager(tmp_path: Path, **kwargs) -> StartupManager:
    cfg = Config()
    cfg.log_dir = str(tmp_path / "logs")
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return StartupManager(cfg)


def test_list_entries_reads_startup_folder(monkeypatch, tmp_path):
    """Без доступа к реестру читается только папка «Автозагрузка»."""
    monkeypatch.setattr(sm_module, "winreg", None)
    (tmp_path / "app.lnk").write_text("x", encoding="utf-8")
    (tmp_path / "desktop.ini").write_text("y", encoding="utf-8")
    (tmp_path / "subfolder").mkdir()

    manager = _manager(tmp_path)
    monkeypatch.setattr(manager, "_startup_dirs", lambda: [tmp_path])

    entries = manager.list_entries()
    assert [e["name"] for e in entries] == ["app"]
    assert entries[0]["type"] == "folder"


def test_disable_folder_entry_moves_file(monkeypatch, tmp_path):
    monkeypatch.setattr(sm_module, "winreg", None)
    source = tmp_path / "tool.lnk"
    source.write_text("x", encoding="utf-8")

    manager = _manager(tmp_path)
    monkeypatch.setattr(manager, "_startup_dirs", lambda: [tmp_path])

    entry = manager.list_entries()[0]
    assert manager.disable_entry(entry) is True
    assert not source.exists()
    assert (tmp_path / "disabled" / "tool.lnk").exists()


def test_run_without_targets_only_analyzes(monkeypatch, tmp_path):
    manager = _manager(tmp_path, startup_disable_entries=[])
    monkeypatch.setattr(manager, "list_entries", lambda: [
        {"name": "app", "command": "cmd", "source": "HKCU\\Run", "type": "registry"}])

    def fail(*args, **kwargs):
        raise AssertionError("отключение не должно вызываться")

    monkeypatch.setattr(manager, "disable_entry", fail)
    report = manager.run()

    assert report["entries"] == [{"name": "app", "source": "HKCU\\Run"}]
    assert report["disabled"] == []


def test_run_disables_only_listed_entries(monkeypatch, tmp_path):
    manager = _manager(tmp_path, startup_disable_entries=["Updater"])
    monkeypatch.setattr(manager, "list_entries", lambda: [
        {"name": "Updater", "command": "x", "source": "HKCU\\Run", "type": "registry"},
        {"name": "KeepMe", "command": "y", "source": "HKCU\\Run", "type": "registry"},
    ])
    called = []

    def fake_disable(entry):
        called.append(entry["name"])
        return True

    monkeypatch.setattr(manager, "disable_entry", fake_disable)
    report = manager.run()

    assert called == ["Updater"]
    assert report["disabled"] == ["Updater"]


def test_run_handles_errors(monkeypatch, tmp_path):
    manager = _manager(tmp_path, startup_disable_entries=["Updater"])
    monkeypatch.setattr(manager, "list_entries", lambda: [
        {"name": "Updater", "command": "x", "source": "HKCU\\Run", "type": "registry"}])
    monkeypatch.setattr(manager, "disable_entry", lambda entry: False)

    report = manager.run()
    assert report["disabled"] == []
    assert report["errors"] == ["Updater"]


def test_registry_roots_available_on_windows(tmp_path):
    manager = _manager(tmp_path)
    if sm_module.winreg is None:
        assert manager._registry_roots() == []
    else:
        roots = manager._registry_roots()
        assert roots
        assert any("Run" in path for _hive, path, _name in roots)

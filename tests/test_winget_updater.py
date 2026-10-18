"""Тесты модуля обновлений winget (src/winget_updater.py)."""
from __future__ import annotations

import json

from src.core.config import Config
from src.advanced.winget_updater import WingetUpdater

WINGET_TABLE = """
Name                          Id                     Version      Available    Source
--------------------------------------------------------------------------------------
Git                           Git.Git                2.40.0       2.42.0       winget
Python 3.12                   Python.Python.3.12     3.12.1       3.12.4       winget
2 upgrades available.
"""


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _updater(tmp_path, **kwargs) -> WingetUpdater:
    cfg = Config()
    cfg.log_dir = str(tmp_path)
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return WingetUpdater(cfg)


def test_available_parses_table(monkeypatch, tmp_path):
    monkeypatch.setattr("src.advanced.winget_updater.shell.run",
                        lambda *a, **k: FakeResult(stdout=WINGET_TABLE))

    updates = _updater(tmp_path).available()
    assert len(updates) == 2
    assert updates[0]["id"] == "Git.Git"
    assert updates[0]["current"] == "2.40.0"
    assert updates[0]["available"] == "2.42.0"
    assert updates[1]["id"] == "Python.Python.3.12"


def test_available_handles_empty_output(monkeypatch, tmp_path):
    monkeypatch.setattr("src.advanced.winget_updater.shell.run", lambda *a, **k: FakeResult(stdout=""))
    assert _updater(tmp_path).available() == []


def test_run_disabled_by_config(monkeypatch, tmp_path):
    updater = _updater(tmp_path, winget_enabled=False)

    def fail(*args, **kwargs):
        raise AssertionError("winget не должен вызываться при выключенном модуле")

    monkeypatch.setattr("src.advanced.winget_updater.shell.run", fail)
    assert updater.run() == {"available": [], "updated": False, "count": 0}


def test_run_lists_only_when_upgrade_disabled(monkeypatch, tmp_path):
    updater = _updater(tmp_path, winget_enabled=True, winget_upgrade_all=False)
    monkeypatch.setattr(updater, "available", lambda: [
        {"name": "Git", "id": "Git.Git", "current": "2.40.0", "available": "2.42.0", "source": "winget"}])

    def fail(*args, **kwargs):
        raise AssertionError("обновление не должно запускаться")

    monkeypatch.setattr("src.advanced.winget_updater.shell.run", fail)
    report = updater.run()
    assert report["count"] == 1
    assert report["updated"] is False
    assert not (tmp_path / "winget_backup.json").exists()


def test_run_upgrades_and_backs_up(monkeypatch, tmp_path):
    updater = _updater(tmp_path, winget_enabled=True, winget_upgrade_all=True)
    monkeypatch.setattr(updater, "available", lambda: [
        {"name": "Git", "id": "Git.Git", "current": "2.40.0", "available": "2.42.0", "source": "winget"}])

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return FakeResult(returncode=0)

    monkeypatch.setattr("src.advanced.winget_updater.shell.run", fake_run)
    report = updater.run()

    assert report["updated"] is True
    assert calls and calls[0][0] == "winget" and "--all" in calls[0]

    backup = json.loads((tmp_path / "winget_backup.json").read_text(encoding="utf-8"))
    assert backup["packages"][0]["id"] == "Git.Git"
    assert backup["packages"][0]["current"] == "2.40.0"


def test_rollback_uses_backup(monkeypatch, tmp_path):
    updater = _updater(tmp_path)
    (tmp_path / "winget_backup.json").write_text(
        json.dumps({"packages": [{"id": "Git.Git", "current": "2.40.0"}]}), encoding="utf-8")

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return FakeResult(returncode=0)

    monkeypatch.setattr("src.advanced.winget_updater.shell.run", fake_run)
    restored = updater.rollback()

    assert restored == ["Git.Git"]
    assert "--version" in calls[0]
    assert "2.40.0" in calls[0]

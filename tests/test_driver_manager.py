"""Тесты управления драйверами."""
from __future__ import annotations

from src.core.config import Config
from src.optimization.driver_manager import DriverManager


def _dm(**kwargs):
    cfg = Config()
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return DriverManager(cfg)


def test_install_from_folder(monkeypatch, tmp_path):
    drv_dir = tmp_path / "drivers"
    drv_dir.mkdir()
    (drv_dir / "a.inf").write_text("[Version]")
    (drv_dir / "b.inf").write_text("[Version]")

    captured = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        captured.append(args)
        return FakeResult()

    monkeypatch.setattr("src.core.system.shell.subprocess.run", fake_run)

    dm = _dm(driver_folder=str(drv_dir))
    installed = dm.install_from_folder()

    assert len(installed) == 2
    assert len(captured) == 2
    assert captured[0][0] == "pnputil"
    assert captured[0][1] == "/add-driver"
    assert captured[0][3] == "/install"


def test_install_from_folder_missing(monkeypatch, tmp_path):
    dm = _dm(driver_folder=str(tmp_path / "nope"))
    assert dm.install_from_folder() == []


def test_delete_driver_force(monkeypatch):
    captured = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("src.core.system.shell.subprocess.run", lambda args, **k: captured.append(args) or FakeResult())

    dm = _dm()
    assert dm.delete_driver("oem0.inf") is True
    assert captured[0] == ["pnputil", "/delete-driver", "oem0.inf", "/force"]


def test_update_all_winget(monkeypatch):
    captured = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("src.core.system.shell.subprocess.run", lambda args, **k: captured.append(args) or FakeResult())

    dm = _dm(driver_update_tool="winget")
    assert dm.update_all() is True
    assert captured[0][0] == "winget"
    assert "upgrade" in captured[0]


def test_update_all_uso(monkeypatch):
    captured = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("src.core.system.shell.subprocess.run", lambda args, **k: captured.append(args) or FakeResult())

    dm = _dm(driver_update_tool="uso")
    assert dm.update_all() is True
    assert captured[0] == ["UsoClient", "ScanInstallWait"]

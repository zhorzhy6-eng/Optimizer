"""Тесты дефрагментации (проверка HDD/SSD и defrag)."""
from __future__ import annotations

from src.core.config import Config
from src.optimization.defragmenter import Defragmenter


def _defrag():
    cfg = Config()
    cfg.defrag_drives = ["C:"]
    return Defragmenter(cfg)


def test_get_drive_media_type_ssd(monkeypatch):
    df = _defrag()

    class FakeResult:
        returncode = 0
        stdout = "SSD"
        stderr = ""

    monkeypatch.setattr("src.core.system.shell.subprocess.run", lambda *a, **k: FakeResult())
    assert df.get_drive_media_type("C:") == "SSD"


def test_get_drive_media_type_hdd(monkeypatch):
    df = _defrag()

    class FakeResult:
        returncode = 0
        stdout = "HDD"
        stderr = ""

    monkeypatch.setattr("src.core.system.shell.subprocess.run", lambda *a, **k: FakeResult())
    assert df.get_drive_media_type("C:") == "HDD"


def test_run_skips_defrag_for_ssd(monkeypatch):
    df = _defrag()
    monkeypatch.setattr(df, "get_drive_media_type", lambda drive: "SSD")

    def fail_if_called(*a, **k):
        raise AssertionError("defragmentation must not run for SSD")

    monkeypatch.setattr(df, "defragment", fail_if_called)
    monkeypatch.setattr(df, "analyze", lambda drive: "")

    report = df.run(["C:"])
    assert report["C:"]["media_type"] == "SSD"
    assert report["C:"]["defragmented"] is False
    assert "SSD" in report["C:"]["reason"]


def test_run_defragments_hdd(monkeypatch):
    df = _defrag()
    monkeypatch.setattr(df, "get_drive_media_type", lambda drive: "HDD")
    monkeypatch.setattr(df, "analyze", lambda drive: "ok")

    calls = []
    monkeypatch.setattr(df, "defragment", lambda drive: calls.append(drive) or True)

    report = df.run(["C:"])
    assert calls == ["C:"]
    assert report["C:"]["defragmented"] is True


def test_run_skips_unknown_media(monkeypatch):
    df = _defrag()
    monkeypatch.setattr(df, "get_drive_media_type", lambda drive: "Unknown")

    def fail_if_called(*a, **k):
        raise AssertionError("defragmentation must not run for unknown media")

    monkeypatch.setattr(df, "defragment", fail_if_called)
    monkeypatch.setattr(df, "analyze", lambda drive: "")

    report = df.run(["C:"])
    assert report["C:"]["defragmented"] is False

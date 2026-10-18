"""Тесты сетевого модуля (src/network_tuner.py)."""
from __future__ import annotations

import json

from src.core.config import Config
from src.advanced.network_tuner import NetworkTuner


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _tuner(tmp_path, **kwargs) -> NetworkTuner:
    cfg = Config()
    cfg.log_dir = str(tmp_path)
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return NetworkTuner(cfg)


def test_flush_dns(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return FakeResult()

    monkeypatch.setattr("src.advanced.network_tuner.shell.run", fake_run)
    assert _tuner(tmp_path).flush_dns() is True
    assert captured["args"] == ["ipconfig", "/flushdns"]


def test_flush_dns_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("src.advanced.network_tuner.shell.run",
                        lambda *a, **k: FakeResult(returncode=1))
    assert _tuner(tmp_path).flush_dns() is False


def test_get_dns_parses_json(monkeypatch, tmp_path):
    payload = json.dumps([{"InterfaceAlias": "Ethernet", "ServerAddresses": ["8.8.8.8", "1.1.1.1"]}])
    monkeypatch.setattr("src.advanced.network_tuner.shell.run",
                        lambda *a, **k: FakeResult(stdout=payload))

    servers = _tuner(tmp_path).get_dns()
    assert servers == [{"interface": "Ethernet", "servers": "8.8.8.8, 1.1.1.1"}]


def test_set_dns_rejects_invalid_addresses(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise AssertionError("команда не должна вызываться при неверных адресах")

    monkeypatch.setattr("src.advanced.network_tuner.shell.run", fail)
    assert _tuner(tmp_path).set_dns(["not-an-ip", "999.999.1.1"]) == []


def test_set_dns_changes_and_backs_up(monkeypatch, tmp_path):
    tuner = _tuner(tmp_path)
    monkeypatch.setattr(tuner, "get_dns",
                        lambda: [{"interface": "Ethernet", "servers": "dhcp"}])
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return FakeResult(returncode=0)

    monkeypatch.setattr("src.advanced.network_tuner.shell.run", fake_run)

    changed = tuner.set_dns(["1.1.1.1", "8.8.8.8"])
    assert changed == ["Ethernet"]
    assert any("Set-DnsClientServerAddress" in " ".join(args) for args in calls)

    backup = json.loads((tmp_path / "network_backup.json").read_text(encoding="utf-8"))
    assert backup["dns"]["Ethernet"] == "dhcp"


def test_restore_dns(monkeypatch, tmp_path):
    tuner = _tuner(tmp_path)
    (tmp_path / "network_backup.json").write_text(
        json.dumps({"dns": {"Ethernet": "192.168.1.1"}}), encoding="utf-8")
    monkeypatch.setattr("src.advanced.network_tuner.shell.run",
                        lambda *a, **k: FakeResult(returncode=0))

    assert tuner.restore_dns() == ["Ethernet"]


def test_tcp_global_parsing(monkeypatch, tmp_path):
    output = (
        "Параметры TCP глобально\n"
        "----------------------------------------------\n"
        "Уровень автонастройки получающего окна : normal\n"
        "Масштабирование окна получателя     : enabled\n"
    )
    monkeypatch.setattr("src.advanced.network_tuner.shell.run",
                        lambda *a, **k: FakeResult(stdout=output))

    params = _tuner(tmp_path).tcp_global()
    assert "normal" in params.get("Уровень автонастройки получающего окна", "")


def test_run_disabled_by_config(monkeypatch, tmp_path):
    tuner = _tuner(tmp_path, network_enabled=False)

    def fail(*args, **kwargs):
        raise AssertionError("при выключенном модуле действия не выполняются")

    monkeypatch.setattr("src.advanced.network_tuner.shell.run", fail)
    report = tuner.run()
    assert report["dns_flushed"] is False


def test_run_flushes_dns_when_enabled(monkeypatch, tmp_path):
    tuner = _tuner(tmp_path, network_enabled=True, network_flush_dns=True,
                   network_set_dns=False, network_tune_tcp=False)
    monkeypatch.setattr("src.advanced.network_tuner.shell.run",
                        lambda *a, **k: FakeResult(returncode=0))
    report = tuner.run()
    assert report["dns_flushed"] is True
    assert report["dns_changed"] == []

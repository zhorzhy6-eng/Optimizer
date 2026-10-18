"""Тесты управления электропитанием."""
from __future__ import annotations

from src.core.config import Config
from src.optimization.power_manager import PowerManager


def _config(**kwargs):
    cfg = Config()
    cfg.game_processes = ["game.exe"]
    cfg.office_processes = ["word.exe"]
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def test_decide_scheme_game_wins():
    pm = PowerManager(_config())
    assert pm.decide_scheme(["game.exe", "word.exe"]) == "high_performance"


def test_decide_scheme_office():
    pm = PowerManager(_config())
    assert pm.decide_scheme(["word.exe"]) == "balanced"


def test_decide_scheme_idle():
    pm = PowerManager(_config())
    assert pm.decide_scheme(["explorer.exe"]) == "power_saver"


def test_decide_scheme_uses_config():
    pm = PowerManager(_config(
        game_scheme="ultimate",
        office_scheme="power_saver",
        idle_scheme="balanced",
    ))
    assert pm.decide_scheme(["game.exe"]) == "ultimate"
    assert pm.decide_scheme(["word.exe"]) == "power_saver"
    assert pm.decide_scheme(["explorer.exe"]) == "balanced"


def test_ultimate_scheme_in_defaults():
    pm = PowerManager(_config())
    assert pm.schemes["ultimate"] == "e9a42b02-d5df-448d-aa00-03f14749eb61"


def test_set_scheme_calls_powercfg(monkeypatch):
    pm = PowerManager(_config())
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        return FakeResult()

    monkeypatch.setattr("src.core.system.shell.subprocess.run", fake_run)

    assert pm.set_scheme("high_performance") is True
    assert captured["args"] == ["powercfg", "/setactive", pm.schemes["high_performance"]]


def test_get_active_scheme_parses_guid(monkeypatch):
    pm = PowerManager(_config())

    class FakeResult:
        returncode = 0
        stdout = "Active Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)"
        stderr = ""

    monkeypatch.setattr("src.core.system.shell.subprocess.run", lambda *a, **k: FakeResult())
    assert pm.get_active_scheme() == "381b4222-f694-41f0-9685-ff5bb260df2e"


def test_list_available_schemes(monkeypatch):
    pm = PowerManager(_config())

    class FakeResult:
        returncode = 0
        stdout = (
            "Existing Power Schemes (* Active)\n"
            "-----------------------------------\n"
            "Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced) *\n"
            "Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (High performance)\n"
        )
        stderr = ""

    monkeypatch.setattr("src.core.system.shell.subprocess.run", lambda *a, **k: FakeResult())

    schemes = pm.list_available_schemes()
    assert len(schemes) == 2
    assert schemes[0]["guid"] == "381b4222-f694-41f0-9685-ff5bb260df2e"
    assert schemes[0]["name"] == "Balanced"
    assert schemes[0]["active"] is True
    assert schemes[1]["active"] is False


def test_apply_best_scheme(monkeypatch):
    pm = PowerManager(_config())
    monkeypatch.setattr(pm, "set_scheme", lambda name: True)
    assert pm.apply_best_scheme(["game.exe"]) == "high_performance"


def test_apply_best_scheme_fallback(monkeypatch):
    """Если выбранная схема недоступна — откат на high_performance."""
    pm = PowerManager(_config(game_scheme="ultimate"))
    calls = []
    monkeypatch.setattr(pm, "set_scheme", lambda name: calls.append(name) or (name == "high_performance"))

    assert pm.apply_best_scheme(["game.exe"]) == "high_performance"
    assert calls == ["ultimate", "high_performance"]

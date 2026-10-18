"""Тесты фонового агента питания (src/advanced/power_agent.py)."""
from __future__ import annotations

import threading
import time

from src.advanced.power_agent import PowerAgent
from src.core import power_context
from src.core.config import Config
from src.optimization.process_monitor import ProcessInfo


def _proc(pid, name, cpu=0.0, mem=0.0):
    return ProcessInfo(pid=pid, name=name, cpu_percent=cpu, memory_percent=mem)


def _agent(tmp_path, **kwargs) -> PowerAgent:
    cfg = Config()
    cfg.log_dir = str(tmp_path)
    cfg.game_processes = ["cs2.exe"]
    cfg.office_processes = ["winword.exe"]
    cfg.heavy_task_processes = ["blender.exe"]
    cfg.launchers_to_ignore = ["steam.exe"]
    cfg.idle_minutes = 10
    cfg.power_agent_game_cooldown_seconds = 180
    cfg.power_agent_enabled = True
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return PowerAgent(cfg)


def _mock_monitor(monkeypatch, procs):
    class FakeMonitor:
        def __init__(self, config, logger=None):
            self.procs = list(procs)

        def list_processes(self, warmup=False, warmup_delay=0):
            return list(self.procs)

    monkeypatch.setattr("src.optimization.process_monitor.ProcessMonitor", FakeMonitor)


def _mock_power(monkeypatch):
    calls = []

    class FakePowerManager:
        def __init__(self, config, logger=None):
            pass

        def set_scheme(self, name):
            calls.append(name)
            return True

    monkeypatch.setattr("src.optimization.power_manager.PowerManager", FakePowerManager)
    return calls


# --------------------------------------------------------------------- #
# Классификация контекста
# --------------------------------------------------------------------- #
def test_classify_game(tmp_path):
    agent = _agent(tmp_path)
    assert agent._classify([_proc(1, "cs2.exe", 45.0)], idle_seconds_value=5) == "game"


def test_classify_game_ignores_launcher(tmp_path):
    """Лаунчер сам по себе игру не включает."""
    agent = _agent(tmp_path)
    result = agent._classify([_proc(2, "steam.exe", 1.0)], idle_seconds_value=5)
    assert result != "game"


def test_classify_office(tmp_path):
    agent = _agent(tmp_path)
    assert agent._classify([_proc(3, "WINWORD.EXE", 10.0)], idle_seconds_value=30) == "office"


def test_classify_heavy(tmp_path):
    agent = _agent(tmp_path)
    assert agent._classify([_proc(4, "blender.exe", 80.0)], idle_seconds_value=0) == "heavy"


def test_classify_heavy_requires_cpu(tmp_path):
    """Низкая загрузка CPU не делает задачу «тяжёлой»."""
    agent = _agent(tmp_path)
    result = agent._classify([_proc(4, "blender.exe", 10.0)], idle_seconds_value=0)
    assert result != "heavy"


def test_classify_idle(tmp_path):
    agent = _agent(tmp_path)
    assert agent._classify([], idle_seconds_value=15 * 60) == "idle"


def test_classify_fallback_keeps_current(tmp_path):
    agent = _agent(tmp_path)
    agent._state["current"] = "office"
    result = agent._classify([_proc(9, "explorer.exe", 1.0)], idle_seconds_value=30)
    assert result == "office"


def test_classify_ignores_pid_zero(tmp_path):
    agent = _agent(tmp_path)
    result = agent._classify([_proc(0, "System Idle Process", 900.0)], idle_seconds_value=5)
    assert result != "heavy"


def test_classify_game_requires_active_user(tmp_path):
    """Игра запущена, но пользователь неактивен > 120 с — не game."""
    agent = _agent(tmp_path)
    result = agent._classify([_proc(1, "cs2.exe", 45.0)], idle_seconds_value=200)
    assert result != "game"


# --------------------------------------------------------------------- #
# Гистерезис
# --------------------------------------------------------------------- #
def test_should_switch_game_immediately(tmp_path):
    agent = _agent(tmp_path)
    agent._state = {"current": "idle", "last_switch": 0.0}
    assert agent._should_switch("game", now=1000.0) is True


def test_should_switch_game_cooldown(tmp_path):
    agent = _agent(tmp_path)
    agent._state = {"current": "game", "last_switch": 1000.0 - 60.0}
    assert agent._should_switch("idle", now=1000.0) is False


def test_should_switch_game_cooldown_expired(tmp_path):
    agent = _agent(tmp_path)
    agent._state = {"current": "game", "last_switch": 1000.0 - 200.0}
    assert agent._should_switch("idle", now=1000.0) is True


def test_should_switch_same_context(tmp_path):
    agent = _agent(tmp_path)
    agent._state = {"current": "game"}
    assert agent._should_switch("game", now=1000.0) is False


def test_should_switch_non_game_contexts_immediately(tmp_path):
    agent = _agent(tmp_path)
    agent._state = {"current": "office", "last_switch": 1000.0 - 5.0}
    assert agent._should_switch("heavy", now=1000.0) is True


# --------------------------------------------------------------------- #
# tick()
# --------------------------------------------------------------------- #
def test_tick_applies_scheme(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    monkeypatch.setattr(agent, "_idle_func", lambda: 5.0)
    _mock_monitor(monkeypatch, [_proc(1, "cs2.exe", 45.0)])
    calls = _mock_power(monkeypatch)

    context = agent.tick()
    assert context == "game"
    assert calls == ["high_performance"]


def test_tick_saves_context(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    monkeypatch.setattr(agent, "_idle_func", lambda: 5.0)
    _mock_monitor(monkeypatch, [_proc(1, "cs2.exe", 45.0)])
    _mock_power(monkeypatch)

    agent.tick()

    state = power_context.load(str(tmp_path))
    assert state["current"] == "game"
    assert state["scheme"] == "high_performance"
    assert state["history"][-1]["context"] == "game"


def test_tick_survives_process_monitor_error(monkeypatch, tmp_path):
    agent = _agent(tmp_path)

    class BrokenMonitor:
        def __init__(self, config, logger=None):
            pass

        def list_processes(self, warmup=False, warmup_delay=0):
            raise RuntimeError("psutil недоступен")

    monkeypatch.setattr("src.optimization.process_monitor.ProcessMonitor", BrokenMonitor)
    assert agent.tick() == "error"  # не упало


def test_tick_no_change_keeps_scheme(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    agent._state = power_context.update({}, "idle", "power_saver", time.time() - 100)
    monkeypatch.setattr(agent, "_idle_func", lambda: 15 * 60.0)
    _mock_monitor(monkeypatch, [])
    calls = _mock_power(monkeypatch)

    context = agent.tick()
    assert context == "idle"
    assert calls == []  # схема не дёргалась


def test_too_many_switches_warning(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    now = time.time()
    state = {}
    for offset in range(5):  # 5 переключений за последнюю минуту
        state = power_context.update(state, "idle", "power_saver", now - 50 + offset)
    agent._state = state

    monkeypatch.setattr(agent, "_idle_func", lambda: 5.0)
    _mock_monitor(monkeypatch, [_proc(1, "cs2.exe", 45.0)])
    calls = _mock_power(monkeypatch)

    assert agent._state["switches_last_minute"] > 3
    context = agent.tick()
    assert context == "game"      # контекст определён
    assert calls == []            # но схема не переключалась (защита)


def test_tick_switches_back_after_cooldown(monkeypatch, tmp_path):
    """game -> idle через cooldown применяет power_saver."""
    agent = _agent(tmp_path)
    agent._state = power_context.update({}, "game", "high_performance", time.time() - 200)
    monkeypatch.setattr(agent, "_idle_func", lambda: 15 * 60.0)
    _mock_monitor(monkeypatch, [])
    calls = _mock_power(monkeypatch)

    context = agent.tick()
    assert context == "idle"
    assert calls == ["power_saver"]


# --------------------------------------------------------------------- #
# Жизненный цикл
# --------------------------------------------------------------------- #
def test_run_forever_stops_on_event(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    monkeypatch.setattr(agent, "tick", lambda: "idle")

    thread = threading.Thread(target=agent.run_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    time.sleep(0.2)
    agent.stop()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert (tmp_path / "power_context.json").exists()  # состояние сохранено при остановке


def test_config_disabled(tmp_path):
    agent = _agent(tmp_path, power_agent_enabled=False)

    def fail(*args, **kwargs):
        raise AssertionError("tick не должен вызываться при выключенном агенте")

    agent.tick = fail
    agent.run_forever()  # завершается сразу, без исключений

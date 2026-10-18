"""Тесты мониторинга процессов."""
from __future__ import annotations

import src.optimization.process_monitor as pm_module
from src.core.config import Config
from src.optimization.process_monitor import ProcessInfo, ProcessMonitor


class FakeProc:
    def __init__(self, pid, name, cpu, mem):
        self.info = {"pid": pid, "name": name}
        self._cpu = cpu
        self._mem = mem
        self.pid = pid
        self.name = name

    def cpu_percent(self, interval=None):
        return self._cpu

    def memory_percent(self):
        return self._mem

    def terminate(self):
        self.terminated = True


def _config(**kwargs):
    cfg = Config()
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def test_list_processes(monkeypatch):
    procs = [FakeProc(1, "a.exe", 10.0, 20.0), FakeProc(2, "b.exe", 5.0, 5.0)]
    monkeypatch.setattr(pm_module.psutil, "process_iter", lambda *a, **k: iter(procs))

    result = ProcessMonitor(_config()).list_processes(warmup=False)
    assert len(result) == 2
    assert isinstance(result[0], ProcessInfo)
    assert result[0].name == "a.exe"


def test_list_processes_skips_system_idle(monkeypatch):
    """System Idle Process (PID 0) — это простой, а не нагрузка."""
    procs = [FakeProc(0, "System Idle Process", 900.0, 0.0), FakeProc(1, "a.exe", 5.0, 1.0)]
    monkeypatch.setattr(pm_module.psutil, "process_iter", lambda *a, **k: iter(procs))

    result = ProcessMonitor(_config()).list_processes(warmup=False)
    assert [p.name for p in result] == ["a.exe"]


def test_list_processes_warmup_initialises_cpu_counters(monkeypatch):
    """Прогрев снимает CPU дважды: иначе первый замер всегда 0.0."""
    class CountingProc:
        def __init__(self, pid, name):
            self.info = {"pid": pid, "name": name}
            self.cpu_calls = 0

        def cpu_percent(self, interval=None):
            self.cpu_calls += 1
            return 7.5

        def memory_percent(self):
            return 1.0

    procs = [CountingProc(1, "a.exe")]
    monkeypatch.setattr(pm_module.psutil, "process_iter", lambda *a, **k: iter(procs))
    monkeypatch.setattr(pm_module.time, "sleep", lambda seconds: None)  # без паузы в тесте

    monitor = ProcessMonitor(_config())

    result = monitor.list_processes()            # с прогревом
    assert len(result) == 1
    assert result[0].cpu_percent == 7.5
    assert procs[0].cpu_calls == 2              # прогрев + замер

    procs[0].cpu_calls = 0
    monitor.list_processes(warmup=False)        # без прогрева
    assert procs[0].cpu_calls == 1


def test_get_heavy_processes():
    cfg = _config(cpu_threshold_percent=50.0, ram_threshold_percent=50.0)
    procs = [
        ProcessInfo(1, "heavy_cpu.exe", 80.0, 10.0),
        ProcessInfo(2, "heavy_ram.exe", 10.0, 90.0),
        ProcessInfo(3, "light.exe", 10.0, 10.0),
    ]
    heavy = ProcessMonitor(cfg).get_heavy_processes(procs)
    assert {p.name for p in heavy} == {"heavy_cpu.exe", "heavy_ram.exe"}


def test_close_unwanted_when_idle(monkeypatch):
    cfg = _config(idle_minutes=10, unwanted_processes=["bad.exe"])
    monitor = ProcessMonitor(cfg)

    # Пользователь неактивен дольше порога.
    monkeypatch.setattr(monitor, "get_idle_seconds", lambda: 11 * 60)

    procs = [
        ProcessInfo(1, "bad.exe", 1.0, 1.0),
        ProcessInfo(2, "good.exe", 1.0, 1.0),
    ]

    terminated = []

    class FakePsutilProcess:
        def __init__(self, pid):
            self.pid = pid
        def terminate(self):
            terminated.append(self.pid)

    monkeypatch.setattr(pm_module.psutil, "Process", FakePsutilProcess)

    closed = monitor.close_unwanted_idle(procs)

    assert closed == ["bad.exe"]
    assert terminated == [1]  # закрыт только нежелательный процесс


def test_close_unwanted_skips_when_active(monkeypatch):
    cfg = _config(idle_minutes=10, unwanted_processes=["bad.exe"])
    monitor = ProcessMonitor(cfg)

    monkeypatch.setattr(monitor, "get_idle_seconds", lambda: 60)  # 1 минута
    procs = [ProcessInfo(1, "bad.exe", 1.0, 1.0)]

    monkeypatch.setattr(pm_module.psutil, "Process", lambda pid: (_ for _ in ()).throw(AssertionError("не должен вызываться")))

    assert monitor.close_unwanted_idle(procs) == []


def test_close_unwanted_only_configured(monkeypatch):
    """Процессы, не перечисленные в списке, не закрываются даже при простое."""
    cfg = _config(idle_minutes=1, unwanted_processes=["bad.exe"])
    monitor = ProcessMonitor(cfg)
    monkeypatch.setattr(monitor, "get_idle_seconds", lambda: 10 * 60)

    procs = [ProcessInfo(1, "system.exe", 1.0, 1.0)]
    monkeypatch.setattr(pm_module.psutil, "Process", lambda pid: (_ for _ in ()).throw(AssertionError("не должен вызываться")))

    assert monitor.close_unwanted_idle(procs) == []

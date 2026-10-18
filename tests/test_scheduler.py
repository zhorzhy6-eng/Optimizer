"""Тесты планировщика."""
from __future__ import annotations

import datetime as dt

import pytest

import src.core.scheduler as sched_module
from src.core.scheduler import TaskScheduler, _SimpleScheduler, parse_time


def test_parse_time_hh_mm():
    assert parse_time("12:00") == dt.time(12, 0)


def test_parse_time_hh_mm_ss():
    assert parse_time("08:30:15") == dt.time(8, 30, 15)


def test_parse_time_invalid():
    with pytest.raises(ValueError):
        parse_time("not-a-time")


def test_simple_scheduler_runs_due_job_once():
    scheduler = _SimpleScheduler()
    calls = []

    now = dt.datetime.now()
    scheduler.daily(now.time().replace(second=0), lambda: calls.append(1))

    scheduler.exec_jobs()
    assert calls == [1]

    # Повторный вызов в ту же минуту не должен дублировать задачу.
    scheduler.exec_jobs()
    assert calls == [1]


def test_simple_scheduler_two_jobs_same_time():
    """Две задачи на одно время выполняются обе (light и full в 12:00)."""
    scheduler = _SimpleScheduler()
    calls = []

    now = dt.datetime.now()
    when = now.time().replace(second=0, microsecond=0)
    scheduler.daily(when, lambda: calls.append("light"))
    scheduler.daily(when, lambda: calls.append("full"))

    scheduler.exec_jobs()
    assert calls == ["light", "full"]

    # и повторно в тот же день не дублируются
    scheduler.exec_jobs()
    assert calls == ["light", "full"]


def test_task_scheduler_registers_daily_times(monkeypatch):
    monkeypatch.setattr(sched_module, "_HAS_SCHEDULER_LIB", False)
    calls = []
    ts = TaskScheduler(["12:00", "18:00"], lambda: calls.append(1))

    assert isinstance(ts._backend, _SimpleScheduler)
    assert len(ts._backend._jobs) == 2
    assert [(h, m) for h, m, _ in ts._backend._jobs] == [(12, 0), (18, 0)]


def test_task_scheduler_add_daily(monkeypatch):
    """Разные функции для разных времён (light/full)."""
    monkeypatch.setattr(sched_module, "_HAS_SCHEDULER_LIB", False)
    ts = TaskScheduler([], func=None)
    ts.add_daily(["12:00"], lambda: None)
    ts.add_daily(["18:00", "20:00"], lambda: None)

    assert isinstance(ts._backend, _SimpleScheduler)
    assert [(h, m) for h, m, _ in ts._backend._jobs] == [(12, 0), (18, 0), (20, 0)]


def test_task_scheduler_safe_run_swallows_errors(monkeypatch):
    monkeypatch.setattr(sched_module, "_HAS_SCHEDULER_LIB", False)

    def boom():
        raise RuntimeError("boom")

    ts = TaskScheduler(["12:00"], boom)
    ts._safe_run()  # не должно поднять исключение

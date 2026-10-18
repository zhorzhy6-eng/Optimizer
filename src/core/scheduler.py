"""Планировщик задач.

Обёртка над библиотекой `scheduler` (PyPI, DigonIO), которая поддерживает
ежедневные и периодические запуски. Если библиотека недоступна (например,
в среде тестирования), используется встроенный запасной планировщик с тем же
интерфейсом, проверяющий расписание по локальному времени.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Callable, List

from .logger import get_logger

try:
    from scheduler import Scheduler as _LibScheduler
    _HAS_SCHEDULER_LIB = True
except Exception:  # pragma: no cover - библиотека опциональна
    _HAS_SCHEDULER_LIB = False

log = get_logger("scheduler")


def parse_time(value: str) -> dt.time:
    """Преобразует "HH:MM" или "HH:MM:SS" в dt.time.

    Raises:
        ValueError: если строка не является корректным временем.
    """
    value = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Некорректное время запуска: {value!r}")


class _SimpleScheduler:
    """Минимальный запасной планировщик (без внешней библиотеки)."""

    def __init__(self) -> None:
        self._jobs: List[tuple[int, int, Callable[[], None]]] = []
        # Ключ включает индекс задачи: иначе две задачи на одно и то же время
        # (например, light и full в 12:00) считались бы одной, и вторая
        # не выполнилась бы вовсе.
        self._last_run: dict[tuple[int, int, int], dt.date] = {}
        # Периодические задачи: (интервал_сек, функция, момент_следующего_запуска).
        self._periodic: List[list] = []

    def daily(self, when: dt.time, func: Callable[[], None]) -> None:
        self._jobs.append((when.hour, when.minute, func))

    def add_periodic(self, seconds: float, func: Callable[[], None]) -> None:
        """Регистрирует задачу, выполняемую каждые seconds секунд."""
        interval = max(1.0, float(seconds))
        self._periodic.append([interval, func, time.time() + interval])

    def exec_jobs(self) -> None:
        now = dt.datetime.now()
        for index, (hour, minute, func) in enumerate(self._jobs):
            key = (hour, minute, index)
            due = dt.datetime.combine(now.date(), dt.time(hour, minute))
            if now >= due and self._last_run.get(key) != now.date():
                self._last_run[key] = now.date()
                func()

        now_ts = time.time()
        for slot in self._periodic:
            interval, func, due = slot
            if now_ts >= due:
                slot[2] = now_ts + interval
                func()


class TaskScheduler:
    """Регистрирует ежедневные запуски функций и выполняет их по расписанию.

    Поддерживает несколько функций: каждое время может вызывать свою задачу
    (например, поверхностную чистку или полную оптимизацию).
    """

    def __init__(
        self,
        times: List[str],
        func: Callable[[], None] | None = None,
        timezone: str | None = None,
    ) -> None:
        self._times = list(times)
        self._func = func
        self._stop_event = threading.Event()
        self._timezone = timezone
        try:
            if _HAS_SCHEDULER_LIB and timezone is None:
                self._backend = _LibScheduler()
            elif _HAS_SCHEDULER_LIB:
                from zoneinfo import ZoneInfo
                self._backend = _LibScheduler(tzinfo=ZoneInfo(timezone))
            else:
                self._backend = _SimpleScheduler()
        except Exception as exc:  # pragma: no cover
            log.warning("Не удалось инициализировать backend планировщика (%s) — использую запасной.", exc)
            self._backend = _SimpleScheduler()

        if func is not None:
            self._register(times, func)

    def _register(self, times: List[str], func: Callable[[], None]) -> None:
        for raw in times:
            try:
                parsed = parse_time(raw)
                self._backend.daily(parsed, lambda: self._safe_run(func))
                log.info("Запланирован ежедневный запуск в %s (%s)",
                         parsed.strftime("%H:%M"), getattr(func, "__name__", repr(func)))
            except ValueError as exc:
                log.error("%s", exc)

    def add_daily(self, times: List[str], func: Callable[[], None]) -> None:
        """Регистрирует дополнительные ежедневные запуски с отдельной функцией."""
        self._register(times, func)

    def add_periodic(self, seconds: float, func: Callable[[], None]) -> None:
        """Регистрирует периодическую задачу (каждые seconds секунд).

        Работает и с запасным планировщиком, и с библиотекой `scheduler`
        (у неё — метод cyclic(timedelta, func)).
        """
        seconds = max(1.0, float(seconds))
        backend = self._backend

        add = getattr(backend, "add_periodic", None)
        if callable(add):
            add(seconds, lambda: self._safe_run(func))
            log.info("Зарегистрирована периодическая задача каждые %.0f с (%s).",
                     seconds, getattr(func, "__name__", repr(func)))
            return

        cyclic = getattr(backend, "cyclic", None)
        if callable(cyclic):
            try:
                cyclic(dt.timedelta(seconds=seconds), lambda: self._safe_run(func))
                log.info("Зарегистрирована периодическая задача каждые %.0f с (%s).",
                         seconds, getattr(func, "__name__", repr(func)))
                return
            except Exception as exc:
                log.warning("Библиотечный backend не принял периодическую задачу: %s", exc)

        log.warning("Backend планировщика не поддерживает периодические задачи")

    def _safe_run(self, func: Callable[[], None] | None = None) -> None:
        target = func if func is not None else self._func
        if target is None:
            return
        try:
            log.info("Планировщик запускает задачу оптимизации.")
            target()
        except Exception as exc:  # задача не должна ронять планировщик
            log.exception("Ошибка при выполнении задачи планировщика: %s", exc)

    def run_forever(self, poll_interval: float = 1.0) -> None:
        """Основной цикл: раз в poll_interval секунд выполняет просроченные задачи."""
        log.info("Планировщик запущен (интервал опроса %.1f с).", poll_interval)
        while not self._stop_event.is_set():
            try:
                self._backend.exec_jobs()
            except Exception as exc:
                log.exception("Ошибка цикла планировщика: %s", exc)
            self._stop_event.wait(poll_interval)

    def run_pending(self) -> None:
        """Выполняет задачи, чей срок наступил (используется для catch-up)."""
        try:
            self._backend.exec_jobs()
        except Exception as exc:
            log.exception("Ошибка run_pending: %s", exc)

    def stop(self) -> None:
        self._stop_event.set()

"""Мониторинг процессов: сбор CPU/RAM, определение тяжёлых процессов,
закрытие нежелательных процессов при простое (idle) пользователя.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

import psutil

from ..core.logger import get_logger
from ..core.system.windows import idle_seconds

log = get_logger("process_monitor")

# System Idle Process (PID 0) показывает долю простоя системы, а не нагрузку,
# поэтому в список процессов и «тяжёлых» он не попадает.
_EXCLUDED_PIDS = frozenset({0})


@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float


class ProcessMonitor:
    """Собирает информацию о процессах и закрывает нежелательные при простое."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log

    # ------------------------------------------------------------------ #
    def _warmup_cpu(self, delay: float) -> None:
        """Первый проход по процессам, инициализирующий счётчики CPU в psutil."""
        try:
            for proc in psutil.process_iter(["pid"]):
                try:
                    proc.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            time.sleep(max(0.0, delay))
        except Exception as exc:
            self.log.debug("Не удалось выполнить прогрев счётчиков CPU: %s", exc)

    def list_processes(self, warmup: bool = True, warmup_delay: float = 0.15) -> List[ProcessInfo]:
        """Возвращает список запущенных процессов с CPU/RAM.

        psutil считает загрузку CPU как разницу между двумя замерами, поэтому
        перед сбором выполняется «прогрев»: значения снимаются дважды с
        небольшой паузой. Без прогрева первый (и обычно единственный) замер
        даёт 0.0 у всех процессов, и «тяжёлые» по CPU не находятся.

        Note:
            cpu_percent — процент загрузки ОДНОГО ядра (как в psutil), поэтому
            на многоядерной системе значение может превышать 100%.
        """
        if warmup:
            self._warmup_cpu(warmup_delay)

        processes: List[ProcessInfo] = []
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    info = proc.info
                    pid = int(info["pid"])
                    if pid in _EXCLUDED_PIDS:
                        continue
                    cpu = proc.cpu_percent(interval=None)
                    mem = proc.memory_percent()
                    processes.append(
                        ProcessInfo(
                            pid=pid,
                            name=str(info["name"] or ""),
                            cpu_percent=float(cpu),
                            memory_percent=float(mem),
                        )
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception as exc:
            self.log.warning("Ошибка сбора списка процессов: %s", exc)

        self.log.info("Собрано процессов: %d.", len(processes))
        return processes

    def get_heavy_processes(self, processes: Optional[List[ProcessInfo]] = None) -> List[ProcessInfo]:
        """Возвращает процессы, превышающие настроенные пороги CPU или RAM."""
        procs = processes if processes is not None else self.list_processes()
        heavy = [
            p for p in procs
            if p.cpu_percent >= self.config.cpu_threshold_percent
            or p.memory_percent >= self.config.ram_threshold_percent
        ]
        for p in heavy:
            self.log.debug("Тяжёлый процесс: %s (PID %s) CPU=%.1f%% RAM=%.1f%%",
                           p.name, p.pid, p.cpu_percent, p.memory_percent)
        self.log.info("Тяжёлых процессов: %d (пороги CPU=%.0f%%, RAM=%.0f%%).",
                      len(heavy), self.config.cpu_threshold_percent, self.config.ram_threshold_percent)
        return heavy

    # ------------------------------------------------------------------ #
    def get_idle_seconds(self) -> float:
        """Возвращает время (сек) с последнего ввода пользователя (Windows)."""
        return idle_seconds()

    def close_unwanted_idle(self, processes: Optional[List[ProcessInfo]] = None) -> List[str]:
        """Закрывает процессы из списка нежелательных, если пользователь неактивен.

        Закрываются ТОЛЬКО процессы, явно перечисленные в конфигурации
        (unwanted_processes). Сравнение имён без учёта регистра.

        Returns:
            список имён закрытых процессов.
        """
        closed: List[str] = []
        try:
            idle = self.get_idle_seconds()
            required = self.config.idle_minutes * 60
            if idle < required:
                self.log.trace("Пользователь активен (idle=%.0f с), закрытие пропущено.", idle)
                return closed

            wanted = {u.lower() for u in self.config.unwanted_processes}
            if not wanted:
                return closed

            procs = processes if processes is not None else self.list_processes()
            for p in procs:
                if p.name.lower() in wanted:
                    try:
                        proc = psutil.Process(p.pid)
                        proc.terminate()
                        wait = getattr(proc, "wait", None)
                        if callable(wait):
                            try:
                                wait(timeout=5)
                            except psutil.TimeoutExpired:
                                self.log.warning("Процесс %s (PID %s) не завершился за 5 с — "
                                                 "принудительное завершение.", p.name, p.pid)
                                proc.kill()
                        closed.append(p.name)
                        self.log.info("Закрыт нежелательный процесс: %s (PID %s).", p.name, p.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                        self.log.debug("Не удалось закрыть %s (PID %s): %s", p.name, p.pid, exc)
                    except Exception as exc:
                        self.log.warning("Ошибка закрытия %s (PID %s): %s", p.name, p.pid, exc)
        except Exception as exc:
            self.log.exception("Неожиданная ошибка close_unwanted_idle: %s", exc)
        return closed

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        """Выполняет полный цикл мониторинга и возвращает отчёт."""
        report = {"process_count": 0, "heavy_processes": [],
                  "closed_processes": []}
        try:
            procs = self.list_processes()
            report["process_count"] = len(procs)
            heavy = self.get_heavy_processes(procs)
            report["heavy_processes"] = [
                {"pid": p.pid, "name": p.name, "cpu": round(p.cpu_percent, 1),
                 "ram": round(p.memory_percent, 1)} for p in heavy
            ]
            report["closed_processes"] = self.close_unwanted_idle(procs)
        except Exception as exc:
            self.log.exception("Неожиданная ошибка ProcessMonitor.run: %s", exc)
        return report

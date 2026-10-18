"""Управление схемой электропитания Windows через powercfg.

Логика выбора схемы:
- активная игра (процесс из game_processes)  -> "Высокая производительность";
- офисная работа (процесс из office_processes) -> "Сбалансированная";
- в остальных случаях (простой)               -> "Экономия энергии".
"""
from __future__ import annotations

import re
import subprocess
from typing import List, Optional

from ..core.system import shell
from ..core.logger import get_logger

log = get_logger("power_manager")

DEFAULT_SCHEMES = {
    "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "power_saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
    "ultimate": "e9a42b02-d5df-448d-aa00-03f14749eb61",
}

_GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class PowerManager:
    """Переключает схемы питания вызовом powercfg."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log
        self.schemes = {**DEFAULT_SCHEMES, **getattr(config, "power_schemes", {})}

    def _run(self, args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        return shell.run(args, timeout=timeout)

    def set_scheme(self, name: str) -> bool:
        """Активирует схему по её внутреннему имени (high_performance и т.п.)."""
        try:
            guid = self.schemes.get(name)
            if guid is None:
                self.log.error("Неизвестная схема питания: %s", name)
                return False
            result = self._run(["powercfg", "/setactive", guid])
            if result.returncode == 0:
                self.log.info("Схема питания переключена на %s (%s).", name, guid)
                return True
            self.log.warning("powercfg /setactive вернул код %s: %s",
                             result.returncode, result.stderr.strip())
            return False
        except Exception as exc:
            self.log.warning("Ошибка переключения схемы питания: %s", exc)
            return False

    def get_active_scheme(self) -> Optional[str]:
        """Возвращает GUID текущей активной схемы (или None)."""
        try:
            result = self._run(["powercfg", "/getactivescheme"])
            match = _GUID_RE.search(result.stdout)
            if match:
                return match.group(0)
            self.log.debug("GUID активной схемы не найден в выводе powercfg.")
            return None
        except Exception as exc:
            self.log.warning("Ошибка получения активной схемы: %s", exc)
            return None

    def decide_scheme(self, process_names: List[str]) -> str:
        """По списку имён процессов выбирает нужную схему питания.

        Имена схем берутся из конфигурации (game_scheme / office_scheme /
        idle_scheme), а не захардкожены.
        """
        names = {n.lower() for n in process_names}
        games = {g.lower() for g in self.config.game_processes}
        office = {o.lower() for o in self.config.office_processes}

        if names & games:
            return getattr(self.config, "game_scheme", "high_performance")
        if names & office:
            return getattr(self.config, "office_scheme", "balanced")
        return getattr(self.config, "idle_scheme", "power_saver")

    def list_available_schemes(self) -> List[dict]:
        """Возвращает доступные в системе схемы питания (powercfg /list).

        Каждый элемент: {"guid": ..., "name": ..., "active": bool}.
        """
        try:
            result = self._run(["powercfg", "/list"])
            schemes: List[dict] = []
            for line in result.stdout.splitlines():
                match = re.search(
                    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\s*\((.+?)\)\s*(\*)?\s*$",
                    line,
                )
                if match:
                    schemes.append({
                        "guid": match.group(1),
                        "name": match.group(2).strip(),
                        "active": bool(match.group(3)),
                    })
            self.log.info("Найдено доступных схем питания: %d.", len(schemes))
            return schemes
        except Exception as exc:
            self.log.warning("Ошибка получения списка схем: %s", exc)
            return []

    def apply_best_scheme(self, process_names: List[str]) -> str:
        """Определяет и применяет подходящую схему; возвращает её имя.

        Если выбранная схема недоступна (например, ultimate), пробует
        откатиться на high_performance.
        """
        scheme = self.decide_scheme(process_names)
        if self.set_scheme(scheme):
            return scheme
        if scheme != "high_performance":
            self.log.warning("Схема %s недоступна — пробую high_performance.", scheme)
            if self.set_scheme("high_performance"):
                return "high_performance"
        return "failed"

    def run(self, process_names: List[str] | None = None) -> dict:
        """Полный цикл: выбор и применение схемы; возвращает отчёт."""
        try:
            if process_names is None:
                from ..optimization.process_monitor import ProcessMonitor
                process_names = [p.name for p in ProcessMonitor(self.config).list_processes()]
            scheme = self.apply_best_scheme(process_names)
            return {"scheme_applied": scheme}
        except Exception as exc:
            self.log.exception("Неожиданная ошибка PowerManager.run: %s", exc)
            return {"scheme_applied": "failed"}

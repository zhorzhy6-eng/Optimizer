"""Температура и троттлинг: наблюдение (и, при желании, реакция схемой питания).

Источники данных:
- `MSAcpi_ThermalZoneTemperature` (WMI, десятые доли Кельвина) —
  доступно не на всех ПК;
- `Win32_PerfFormattedData_Counters_ThermalZoneInformation` (Кельвины*10);
- `psutil.cpu_freq()` и `Win32_Processor` — текущая и максимальная частота.

Модуль только читает данные и пишет предупреждения. Единственное действие —
необязательный перевод схемы питания в «Экономию энергии» при перегреве,
и только если это разрешено в конфиге.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import psutil

from ..core.system import shell
from ..core.logger import get_logger

log = get_logger("thermal_monitor")


class ThermalMonitor:
    """Следит за температурой и признаками троттлинга."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log

    # ------------------------------------------------------------------ #
    # Температура
    # ------------------------------------------------------------------ #
    def temperatures(self) -> List[Dict[str, object]]:
        """Температуры датчиков в градусах Цельсия."""
        readings: List[Dict[str, object]] = []

        # Основной источник: деciKelvin через WMI.
        data = self._query(
            "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
            "-ErrorAction SilentlyContinue | "
            "Select-Object InstanceName,CurrentTemperature | ConvertTo-Json -Compress"
        )
        for item in data or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("CurrentTemperature")
            if isinstance(raw, (int, float)) and raw > 0:
                celsius = round(raw / 10.0 - 273.15, 1)
                if -50 < celsius < 150:
                    readings.append({"sensor": str(item.get("InstanceName", "ACPI")),
                                     "celsius": celsius})

        # Резервный источник: счётчики производительности.
        if not readings:
            data = self._query(
                "Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation "
                "-ErrorAction SilentlyContinue | Select-Object Name,Temperature | "
                "ConvertTo-Json -Compress"
            )
            for item in data or []:
                if not isinstance(item, dict):
                    continue
                raw = item.get("Temperature")
                if isinstance(raw, (int, float)) and raw > 0:
                    celsius = round(raw / 10.0 - 273.15, 1)
                    if -50 < celsius < 150:
                        readings.append({"sensor": str(item.get("Name", "ThermalZone")),
                                         "celsius": celsius})
        return readings

    def _query(self, command: str):
        try:
            result = shell.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command], timeout=120)
            raw = (result.stdout or "").strip()
            if not raw:
                return None
            data = json.loads(raw)
        except Exception as exc:
            self.log.debug("Ошибка запроса температуры: %s", exc)
            return None
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else None

    # ------------------------------------------------------------------ #
    # Частота и троттлинг
    # ------------------------------------------------------------------ #
    def cpu_clock(self) -> Dict[str, float]:
        """Текущая и максимальная частота CPU, МГц."""
        current = maximum = 0.0
        try:
            freq = psutil.cpu_freq()
            if freq:
                current = float(freq.current or 0.0)
                maximum = float(freq.max or 0.0)
        except Exception as exc:
            self.log.debug("psutil.cpu_freq недоступен: %s", exc)

        if maximum <= 0:
            data = self._query(
                "Get-CimInstance Win32_Processor | "
                "Select-Object CurrentClockSpeed,MaxClockSpeed | ConvertTo-Json -Compress"
            )
            for item in data or []:
                if isinstance(item, dict):
                    current = current or float(item.get("CurrentClockSpeed") or 0)
                    maximum = float(item.get("MaxClockSpeed") or 0)
                    break
        return {"current_mhz": round(current, 1), "max_mhz": round(maximum, 1)}

    def is_throttling(self, clock: Optional[Dict[str, float]] = None) -> bool:
        """Признак троттлинга: частота ниже заданного процента от максимума."""
        clock = clock or self.cpu_clock()
        current, maximum = clock.get("current_mhz", 0.0), clock.get("max_mhz", 0.0)
        if current <= 0 or maximum <= 0:
            return False
        threshold = float(getattr(self.config, "thermal_min_clock_percent", 60.0) or 0.0)
        return (current / maximum * 100.0) < threshold

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        """Собирает температуру и состояние троттлинга."""
        report: dict = {"temperatures": [], "clock": {}, "throttling": False,
                        "max_temperature": 0.0, "warnings": [], "power_scheme": ""}
        try:
            report["temperatures"] = self.temperatures()
            report["clock"] = self.cpu_clock()
            report["throttling"] = self.is_throttling(report["clock"])

            if report["temperatures"]:
                report["max_temperature"] = max(t["celsius"] for t in report["temperatures"])

            limit = float(getattr(self.config, "thermal_max_temperature_c", 85.0) or 0.0)
            if report["max_temperature"] and limit and report["max_temperature"] >= limit:
                message = f"Температура {report['max_temperature']} °C превышает порог {limit} °C"
                report["warnings"].append(message)
                self.log.warning("%s", message)

            if report["throttling"]:
                message = (f"Признак троттлинга: {report['clock'].get('current_mhz')} МГц из "
                           f"{report['clock'].get('max_mhz')} МГц")
                report["warnings"].append(message)
                self.log.warning("%s", message)

            if report["warnings"] and getattr(self.config, "thermal_switch_to_power_saver", False):
                report["power_scheme"] = self._switch_to_power_saver()

            self.log.info("Температур: %d, максимум %.1f °C, троттлинг: %s.",
                          len(report["temperatures"]), report["max_temperature"],
                          report["throttling"])
        except Exception as exc:
            self.log.exception("Неожиданная ошибка ThermalMonitor.run: %s", exc)
            report["warnings"].append(str(exc))
        return report

    def _switch_to_power_saver(self) -> str:
        """Переводит схему питания в «Экономию энергии» при перегреве."""
        try:
            from ..optimization.power_manager import PowerManager

            manager = PowerManager(self.config, logger=self.log)
            scheme = getattr(self.config, "idle_scheme", "power_saver")
            if manager.set_scheme(scheme):
                self.log.warning("Из-за температуры схема питания переключена на %s.", scheme)
                return scheme
        except Exception as exc:
            self.log.warning("Не удалось переключить схему питания: %s", exc)
        return ""

"""Здоровье дисков: SMART-состояние, износ и свободное место.

Модуль только читает данные (Get-PhysicalDisk, Get-Volume,
Get-StorageReliabilityCounter), поэтому безопасен и включён по умолчанию.
Предупреждения пишутся в лог и в отчёт, никакие действия не выполняются.
"""
from __future__ import annotations

import json
from typing import Dict, List

from ..core.system import shell
from ..core.logger import get_logger

log = get_logger("disk_health")


class DiskHealth:
    """Собирает состояние дисков и томов."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log

    # ------------------------------------------------------------------ #
    def _query(self, command: str, timeout: int = 120):
        try:
            result = shell.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                timeout=timeout,
            )
        except Exception as exc:
            self.log.debug("Ошибка запроса: %s", exc)
            return None
        raw = (result.stdout or "").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except Exception as exc:
            self.log.debug("Не удалось разобрать ответ: %s", exc)
            return None
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else None

    def physical_disks(self) -> List[Dict[str, str]]:
        """Физические диски: модель, тип носителя, здоровье."""
        data = self._query(
            "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,HealthStatus,"
            "OperationalStatus,Size | ConvertTo-Json -Compress"
        )
        disks: List[Dict[str, str]] = []
        for item in data or []:
            if not isinstance(item, dict):
                continue
            size = item.get("Size")
            disks.append({
                "name": str(item.get("FriendlyName", "")),
                "media_type": str(item.get("MediaType", "")),
                "health": str(item.get("HealthStatus", "")),
                "status": str(item.get("OperationalStatus", "")),
                "size_gb": round(int(size) / 1024 ** 3, 1) if isinstance(size, (int, float)) else 0.0,
            })
        return disks

    def volumes(self) -> List[Dict[str, str]]:
        """Логические тома: свободное место."""
        data = self._query(
            "Get-Volume | Where-Object { $_.DriveLetter } | Select-Object DriveLetter,"
            "FileSystemLabel,Size,SizeRemaining | ConvertTo-Json -Compress"
        )
        volumes: List[Dict[str, str]] = []
        for item in data or []:
            if not isinstance(item, dict):
                continue
            size = item.get("Size") or 0
            free = item.get("SizeRemaining") or 0
            free_percent = round(free / size * 100, 1) if size else 0.0
            volumes.append({
                "drive": f"{item.get('DriveLetter', '')}:",
                "label": str(item.get("FileSystemLabel", "") or ""),
                "size_gb": round(size / 1024 ** 3, 1) if size else 0.0,
                "free_gb": round(free / 1024 ** 3, 1) if free else 0.0,
                "free_percent": free_percent,
            })
        return volumes

    def reliability(self) -> List[Dict[str, str]]:
        """Дополнительные счётчики надёжности (может быть недоступно)."""
        data = self._query(
            "Get-PhysicalDisk | Get-StorageReliabilityCounter | "
            "Select-Object DeviceId,Temperature,ReadErrorsTotal,WriteErrorsTotal,Wear | "
            "ConvertTo-Json -Compress"
        )
        counters: List[Dict[str, str]] = []
        for item in data or []:
            if not isinstance(item, dict):
                continue
            counters.append({
                "device": str(item.get("DeviceId", "")),
                "temperature_c": item.get("Temperature"),
                "read_errors": item.get("ReadErrorsTotal"),
                "write_errors": item.get("WriteErrorsTotal"),
                "wear": item.get("Wear"),
            })
        return counters

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        """Собирает состояние дисков и формирует предупреждения."""
        report: dict = {"disks": [], "volumes": [], "warnings": []}
        try:
            report["disks"] = self.physical_disks()
            report["volumes"] = self.volumes()

            for disk in report["disks"]:
                health = (disk.get("health") or "").lower()
                if health and health not in ("healthy", "здоров"):
                    message = f"Диск {disk.get('name')}: состояние {disk.get('health')}"
                    report["warnings"].append(message)
                    self.log.warning("%s", message)

            warn_percent = float(getattr(self.config, "disk_health_warn_free_percent", 10.0) or 0)
            for volume in report["volumes"]:
                if volume["free_percent"] and volume["free_percent"] < warn_percent:
                    message = (f"Том {volume['drive']}: свободно "
                               f"{volume['free_gb']} ГБ ({volume['free_percent']}%)")
                    report["warnings"].append(message)
                    self.log.warning("%s", message)

            self.log.info("Дисков: %d, томов: %d, предупреждений: %d.",
                          len(report["disks"]), len(report["volumes"]), len(report["warnings"]))
        except Exception as exc:
            self.log.exception("Неожиданная ошибка DiskHealth.run: %s", exc)
            report["warnings"].append(str(exc))
        return report

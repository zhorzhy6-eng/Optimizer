"""Дефрагментация дисков.

Перед запуском обязательно определяется тип носителя (SSD/HDD):
дефрагментация выполняется ТОЛЬКО для HDD. Для SSD операция пропускается,
т.к. она бесполезна и сокращает срок службы накопителя.
Анализ фрагментации выполняется командой: defrag.exe <drive> /A /V /U
"""
from __future__ import annotations

import subprocess
from typing import List, Optional

from ..core.system import shell
from ..core.logger import get_logger

log = get_logger("defragmenter")


class Defragmenter:
    """Анализирует фрагментацию и дефрагментирует только HDD-диски."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log

    def _run(self, args: List[str], timeout: int = 3600) -> subprocess.CompletedProcess:
        return shell.run(args, timeout=timeout)

    # ------------------------------------------------------------------ #
    def get_drive_media_type(self, drive: str) -> str:
        """Возвращает тип носителя для буквы диска: 'SSD', 'HDD' или 'Unknown'.

        Используется PowerShell: Get-Partition -> Get-Disk -> Get-PhysicalDisk.
        """
        letter = drive.rstrip(":\\").upper()[:1]
        script = (
            f"$p = Get-Partition -DriveLetter {letter} -ErrorAction SilentlyContinue; "
            "if ($p) { ($p | Get-Disk | Get-PhysicalDisk).MediaType } "
            "else { 'Unknown' }"
        )
        try:
            result = self._run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=60)
            media_type = (result.stdout or "").strip()
            if not media_type:
                return "Unknown"
            media_type_l = media_type.lower()
            if "ssd" in media_type_l or "scm" in media_type_l:
                return "SSD"
            if "hdd" in media_type_l:
                return "HDD"
            return "Unknown"
        except Exception as exc:
            self.log.warning("Не удалось определить тип диска %s: %s", drive, exc)
            return "Unknown"

    def is_ssd(self, drive: str) -> bool:
        return self.get_drive_media_type(drive).upper() == "SSD"

    # ------------------------------------------------------------------ #
    def analyze(self, drive: str) -> str:
        """Запускает анализ фрагментации: defrag.exe <drive> /A /V /U."""
        try:
            result = self._run(["defrag.exe", drive, "/A", "/V", "/U"])
            output = (result.stdout or "") + (result.stderr or "")
            self.log.info("Анализ фрагментации %s завершён (код %s).", drive, result.returncode)
            self.log.trace("Вывод defrag /A для %s:\n%s", drive, output)
            return output
        except Exception as exc:
            self.log.warning("Ошибка анализа фрагментации %s: %s", drive, exc)
            return ""

    def defragment(self, drive: str) -> bool:
        """Запускает дефрагментацию диска (вызывать ТОЛЬКО для HDD)."""
        try:
            self.log.info("Запуск дефрагментации диска %s...", drive)
            result = self._run(["defrag.exe", drive, "/O", "/V"])
            ok = result.returncode == 0
            self.log.info("Дефрагментация %s завершена: %s.", drive, "успешно" if ok else f"код {result.returncode}")
            self.log.trace("Вывод defrag для %s:\n%s", drive, (result.stdout or "") + (result.stderr or ""))
            return ok
        except Exception as exc:
            self.log.warning("Ошибка дефрагментации %s: %s", drive, exc)
            return False

    # ------------------------------------------------------------------ #
    def run(self, drives: List[str] | None = None) -> dict:
        """Анализирует и (при необходимости) дефрагментирует переданные диски.

        Returns:
            отчёт: {drive: {"media_type": ..., "defragmented": bool, "reason": ...}}
        """
        report: dict = {}
        targets = drives if drives is not None else self.config.defrag_drives

        for drive in targets:
            entry: dict = {"media_type": "Unknown", "defragmented": False, "reason": ""}
            try:
                media_type = self.get_drive_media_type(drive)
                entry["media_type"] = media_type

                if media_type.upper() == "SSD":
                    entry["reason"] = "SSD — дефрагментация пропущена (вредна для накопителя)"
                    self.log.warning("Диск %s — SSD. Дефрагментация пропущена (вредна для накопителя).", drive)
                elif media_type.upper() == "HDD":
                    self.analyze(drive)
                    entry["defragmented"] = self.defragment(drive)
                    entry["reason"] = "дефрагментация выполнена" if entry["defragmented"] else "ошибка дефрагментации"
                else:
                    entry["reason"] = "тип диска не определён — пропуск из соображений безопасности"
                    self.log.warning("Тип диска %s не определён — дефрагментация пропущена.", drive)
            except Exception as exc:
                entry["reason"] = f"ошибка: {exc}"
                self.log.exception("Ошибка обработки диска %s: %s", drive, exc)
            report[drive] = entry

        return report

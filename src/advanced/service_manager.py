"""Службы Windows: анализ и безопасное управление типом запуска.

Безопасность:
- критичные службы защищены встроенным списком (`CRITICAL_SERVICES`) —
  их тип запуска не меняется никогда, даже если они указаны в конфиге;
- изменяются только службы из `services.disable_services`;
- перед изменением прежний тип запуска сохраняется в
  `logs/services_backup.json`, поэтому `restore_services()` может вернуть всё как было.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Union

from ..core.system import shell
from ..core.logger import get_logger

log = get_logger("service_manager")

# Службы, изменение которых ломает систему или сеть. Не трогаем никогда.
CRITICAL_SERVICES = frozenset({
    # Ядро RPC/DCOM/питание/PnP
    "rpcss", "rpcpptmapper", "dcomlaunch", "plugplay", "power", "brokerinfrastructure",
    "systemeventsbroker", "lsm", "samss", "winmgmt", "eventlog", "eventsystem",
    # Планировщик и профили
    "schedule", "profsvc", "usermanager", "themes", "gpsvc",
    # Сеть и безопасность
    "dhcp", "dnscache", "nsi", "nlasvc", "lanmanworkstation", "lanmanserver",
    "wlandsvc", "wlansvc", "mpssvc", "bfe", "cryptsvc", "seclogon",
    # Звук, оболочка, устройства
    "audiosrv", "audioendpointbuilder", "shellhwdetection", "spooler",
    # Обновления и защита
    "wuauserv", "bits", "windefend", "securityhealthservice", "wscsvc",
    # Время и журналы
    "w32time", "wecsvc", "diagsvc", "trustedinstaller",
})

# Режимы ручного запуска в разных представлениях (Win32_Service и sc.exe).
MANUAL_MODES = {"manual", "demand", "вручную", "3", "demand_start"}


class ServiceManager:
    """Читает список служб и (при явном разрешении) меняет тип запуска."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log
        self.backup_path = Path(getattr(config, "log_dir", "logs")) / "services_backup.json"

    # ------------------------------------------------------------------ #
    # Анализ
    # ------------------------------------------------------------------ #
    def _protected(self) -> set:
        extra = {str(name).strip().lower() for name in getattr(self.config, "services_protected", [])}
        return set(CRITICAL_SERVICES) | extra

    def list_services(self) -> List[Dict[str, str]]:
        """Возвращает службы с типом запуска и состоянием (только чтение)."""
        command = (
            "Get-CimInstance Win32_Service | "
            "Select-Object Name,DisplayName,StartMode,State | ConvertTo-Json -Compress"
        )
        try:
            result = shell.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                timeout=180,
            )
        except Exception as exc:
            self.log.warning("Не удалось получить список служб: %s", exc)
            return []

        raw = (result.stdout or "").strip()
        if not raw:
            self.log.warning("Пустой ответ при получении списка служб.")
            return []
        try:
            data = json.loads(raw)
        except Exception as exc:
            self.log.warning("Не удалось разобрать список служб: %s", exc)
            return []
        if isinstance(data, dict):
            data = [data]

        services: List[Dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            services.append({
                "name": str(item.get("Name", "")),
                "display_name": str(item.get("DisplayName", "")),
                "start_mode": str(item.get("StartMode", "")),
                "state": str(item.get("State", "")),
            })
        self.log.info("Служб получено: %d.", len(services))
        return services

    # ------------------------------------------------------------------ #
    # Изменение типа запуска
    # ------------------------------------------------------------------ #
    def _load_backup(self) -> dict:
        try:
            if self.backup_path.exists():
                return json.loads(self.backup_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            self.log.debug("Не удалось прочитать %s: %s", self.backup_path, exc)
        return {}

    def _save_backup(self, data: dict) -> None:
        try:
            self.backup_path.parent.mkdir(parents=True, exist_ok=True)
            self.backup_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.log.warning("Не удалось сохранить %s: %s", self.backup_path, exc)

    def set_start_mode(self, name: str, mode: str = "Manual") -> bool:
        """Меняет тип запуска службы, сохраняя прежний в резервный файл."""
        if name.strip().lower() in self._protected():
            self.log.warning("Служба %s защищена — изменение отменено.", name)
            return False
        try:
            current = self._current_mode(name)
            if current is None:
                self.log.warning("Служба %s не найдена.", name)
                return False
            if current.lower() in MANUAL_MODES:
                self.log.info("Служба %s уже в режиме ручного запуска.", name)
                return True

            backup = self._load_backup()
            backup.setdefault(name, {"start_mode": current})
            self._save_backup(backup)

            result = shell.run(["sc.exe", "config", name, "start=", "demand"], timeout=60)
            if result.returncode == 0:
                self.log.info("Служба %s переведена в ручной запуск (было: %s).", name, current)
                return True
            self.log.warning("Не удалось изменить службу %s (код %s): %s",
                             name, result.returncode, (result.stderr or "").strip())
            return False
        except Exception as exc:
            self.log.warning("Ошибка изменения службы %s: %s", name, exc)
            return False

    def _current_mode(self, name: str) -> Optional[str]:
        try:
            result = shell.run(["sc.exe", "qc", name], timeout=60)
            for line in (result.stdout or "").splitlines():
                if "START_TYPE" in line.upper():
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        return parts[1].strip().split()[0]
        except Exception as exc:
            self.log.debug("Не удалось получить тип запуска %s: %s", name, exc)
        return None

    @staticmethod
    def _mode_to_sc_value(mode: str) -> str:
        """Переводит сохранённый режим в значение для `sc.exe config start=`."""
        normalized = str(mode).strip().lower()
        if normalized.startswith("auto") or normalized in ("2", "auto_start"):
            return "auto"
        if normalized.startswith("disab") or normalized in ("4", "disabled"):
            return "disabled"
        return "demand"

    def restore_services(self) -> List[str]:
        """Возвращает прежние типы запуска из резервного файла."""
        restored: List[str] = []
        backup = self._load_backup()
        for name, info in list(backup.items()):
            value = self._mode_to_sc_value(info.get("start_mode", "auto"))
            try:
                result = shell.run(["sc.exe", "config", name, "start=", value], timeout=60)
                if result.returncode == 0:
                    restored.append(name)
                    backup.pop(name, None)
            except Exception as exc:
                self.log.warning("Не удалось вернуть службу %s: %s", name, exc)
        self._save_backup(backup)
        return restored

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        """Анализ служб и перевод разрешённых в ручной запуск."""
        report: dict = {"total": 0, "changed": [], "skipped_protected": [], "errors": []}
        try:
            services = self.list_services()
            report["total"] = len(services)

            targets = {name.strip().lower() for name in self.config.services_disable if name.strip()}
            if not targets:
                self.log.info("Список служб для отключения пуст — только анализ.")
                return report

            for service in services:
                name = service["name"]
                if name.lower() not in targets:
                    continue
                if name.lower() in self._protected():
                    report["skipped_protected"].append(name)
                    self.log.warning("Служба %s в защищённом списке — пропуск.", name)
                    continue
                if self.set_start_mode(name, "Manual"):
                    report["changed"].append(name)
                else:
                    report["errors"].append(name)
        except Exception as exc:
            self.log.exception("Неожиданная ошибка ServiceManager.run: %s", exc)
            report["errors"].append(str(exc))
        return report

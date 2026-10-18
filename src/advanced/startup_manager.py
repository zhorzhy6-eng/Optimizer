"""Автозагрузка: анализ и обратимое отключение записей.

Источники:
- реестр HKCU/HKLM `...\\CurrentVersion\\Run` и `RunOnce`
  (включая 32-битную ветку Wow6432Node);
- папки «Автозагрузка» пользователя и общая.

Безопасность:
- отключение выполняется ТОЛЬКО для имён из `startup.disable_entries`;
- отключение обратимо: значение реестра переносится в резервный ключ
  `<Run>_disabled_by_optimizer`, файл из папки «Автозагрузка» — в подпапку
  `disabled`, поэтому запись можно вернуть методом `enable_entry`.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from ..core.system import safety
from ..core.logger import get_logger

log = get_logger("startup_manager")

try:
    import winreg  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - не Windows
    winreg = None  # type: ignore[assignment]

BACKUP_SUFFIX = "_disabled_by_optimizer"


class StartupManager:
    """Читает автозагрузку и (при явном разрешении) отключает записи."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log

    # ------------------------------------------------------------------ #
    # Пути и ключи
    # ------------------------------------------------------------------ #
    def _startup_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        appdata = os.environ.get("APPDATA")
        programdata = os.environ.get("ProgramData")
        if appdata:
            dirs.append(Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup")
        if programdata:
            dirs.append(Path(programdata) / "Microsoft/Windows/Start Menu/Programs/Startup")
        return dirs

    def _registry_roots(self) -> List[tuple]:
        """Пары (корень реестра, путь ключа Run/RunOnce)."""
        if winreg is None:
            return []
        paths = [
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
            r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Run",
        ]
        roots = []
        for hive, hive_name in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
            for path in paths:
                roots.append((hive, path, hive_name))
        return roots

    # ------------------------------------------------------------------ #
    # Анализ
    # ------------------------------------------------------------------ #
    def list_entries(self) -> List[Dict[str, str]]:
        """Возвращает список записей автозагрузки."""
        entries: List[Dict[str, str]] = []

        if winreg is not None:
            for hive, path, hive_name in self._registry_roots():
                try:
                    with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                        index = 0
                        while True:
                            try:
                                name, value, _kind = winreg.EnumValue(key, index)
                            except OSError:
                                break
                            entries.append({
                                "name": str(name),
                                "command": str(value),
                                "source": f"{hive_name}\\{path}",
                                "type": "registry",
                            })
                            index += 1
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    self.log.debug("Не удалось прочитать %s\\%s: %s", hive_name, path, exc)

        for directory in self._startup_dirs():
            try:
                if not directory.is_dir():
                    continue
                for item in directory.iterdir():
                    if item.name.lower() == "desktop.ini" or item.is_dir():
                        continue
                    entries.append({
                        "name": item.stem,
                        "command": str(item),
                        "source": str(directory),
                        "type": "folder",
                    })
            except Exception as exc:
                self.log.debug("Не удалось прочитать %s: %s", directory, exc)

        self.log.info("Записей автозагрузки найдено: %d.", len(entries))
        return entries

    # ------------------------------------------------------------------ #
    # Отключение / возврат
    # ------------------------------------------------------------------ #
    def disable_entry(self, entry: Dict[str, str]) -> bool:
        """Отключает запись автозагрузки (обратимо)."""
        try:
            if entry.get("type") == "registry":
                return self._disable_registry_entry(entry)
            if entry.get("type") == "folder":
                return self._disable_folder_entry(entry)
            return False
        except Exception as exc:
            self.log.warning("Не удалось отключить %s: %s", entry.get("name"), exc)
            return False

    def _disable_registry_entry(self, entry: Dict[str, str]) -> bool:
        if winreg is None:
            return False
        hive_name, _, path = entry["source"].partition("\\")
        hive = winreg.HKEY_CURRENT_USER if hive_name == "HKCU" else winreg.HKEY_LOCAL_MACHINE
        backup_path = path + BACKUP_SUFFIX
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                value, value_type = winreg.QueryValueEx(key, entry["name"])
            with winreg.CreateKeyEx(hive, backup_path, 0, winreg.KEY_WRITE) as backup:
                winreg.SetValueEx(backup, entry["name"], 0, value_type, value)
            with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, entry["name"])
            self.log.info("Запись автозагрузки отключена: %s (%s)", entry["name"], entry["source"])
            return True
        except Exception as exc:
            self.log.warning("Не удалось отключить %s: %s", entry["name"], exc)
            return False

    def enable_entry(self, entry: Dict[str, str]) -> bool:
        """Возвращает ранее отключённую запись реестра на место."""
        if winreg is None or entry.get("type") != "registry":
            return False
        hive_name, _, path = entry["source"].partition("\\")
        hive = winreg.HKEY_CURRENT_USER if hive_name == "HKCU" else winreg.HKEY_LOCAL_MACHINE
        backup_path = path + BACKUP_SUFFIX
        try:
            with winreg.OpenKey(hive, backup_path, 0, winreg.KEY_READ) as backup:
                value, value_type = winreg.QueryValueEx(backup, entry["name"])
            with winreg.CreateKeyEx(hive, path, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, entry["name"], 0, value_type, value)
            with winreg.OpenKey(hive, backup_path, 0, winreg.KEY_SET_VALUE) as backup:
                winreg.DeleteValue(backup, entry["name"])
            self.log.info("Запись автозагрузки включена обратно: %s", entry["name"])
            return True
        except Exception as exc:
            self.log.warning("Не удалось вернуть %s: %s", entry["name"], exc)
            return False

    def _disable_folder_entry(self, entry: Dict[str, str]) -> bool:
        source = Path(entry["command"])
        if not source.exists() or safety.is_protected(source.parent):
            return False
        disabled_dir = source.parent / "disabled"
        disabled_dir.mkdir(exist_ok=True)
        target = disabled_dir / source.name
        shutil.move(str(source), str(target))
        self.log.info("Файл автозагрузки перемещён: %s -> %s", source, target)
        return True

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        """Анализ автозагрузки и отключение разрешённых записей."""
        report: dict = {"entries": [], "disabled": [], "errors": []}
        try:
            entries = self.list_entries()
            report["entries"] = [
                {"name": e["name"], "source": e["source"]} for e in entries
            ]

            targets = {name.strip().lower() for name in self.config.startup_disable_entries if name.strip()}
            if not targets:
                self.log.info("Список отключаемых записей автозагрузки пуст — только анализ.")
                return report

            for entry in entries:
                if entry["name"].strip().lower() in targets:
                    if self.disable_entry(entry):
                        report["disabled"].append(entry["name"])
                    else:
                        report["errors"].append(entry["name"])
        except Exception as exc:
            self.log.exception("Неожиданная ошибка StartupManager.run: %s", exc)
            report["errors"].append(str(exc))
        return report

"""Обновления пакетов через winget с возможностью отката.

Безопасность:
- по умолчанию модуль выключен и только перечисляет доступные обновления;
- фактическое обновление выполняется лишь при `winget.upgrade_all: true`;
- перед обновлением список пакетов с текущими версиями сохраняется в
  `logs/winget_backup.json`, а `rollback()` пытается вернуть прежние версии
  через `winget install --id <id> --version <версия>`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

from ..core.system import shell
from ..core.logger import get_logger

log = get_logger("winget_updater")

_COLUMN_SPLIT = re.compile(r"\s{2,}")
_HEADER_HINTS = ("name", "id", "version", "available", "source")


class WingetUpdater:
    """Проверяет и (по разрешению) устанавливает обновления winget."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log
        self.backup_path = Path(getattr(config, "log_dir", "logs")) / "winget_backup.json"

    # ------------------------------------------------------------------ #
    def available(self) -> List[Dict[str, str]]:
        """Список доступных обновлений (парсинг таблицы winget upgrade)."""
        try:
            result = shell.run([
                "winget", "upgrade", "--include-unknown",
                "--accept-source-agreements",
            ], timeout=600)
        except Exception as exc:
            self.log.warning("Ошибка вызова winget: %s", exc)
            return []

        output = result.stdout or ""
        if result.returncode != 0 and not output:
            self.log.warning("winget вернул код %s: %s", result.returncode, (result.stderr or "").strip())
            return []

        lines = [line.rstrip() for line in output.splitlines()]
        header_index = None
        for index, line in enumerate(lines):
            lowered = line.lower()
            if all(hint in lowered for hint in ("id", "version")) and "available" in lowered:
                header_index = index
                break
        if header_index is None:
            self.log.debug("Заголовок таблицы winget не найден.")
            return []

        updates: List[Dict[str, str]] = []
        for line in lines[header_index + 1:]:
            if not line.strip() or set(line.strip()) <= {"-"}:
                continue
            lowered = line.lower()
            if lowered.startswith(("upgrades available", "обновлен", "доступн")):
                break
            parts = _COLUMN_SPLIT.split(line.strip())
            if len(parts) < 4:
                continue
            updates.append({
                "name": parts[0],
                "id": parts[1],
                "current": parts[2],
                "available": parts[3],
                "source": parts[4] if len(parts) > 4 else "",
            })
        self.log.info("Доступно обновлений winget: %d.", len(updates))
        return updates

    # ------------------------------------------------------------------ #
    def _save_backup(self, updates: List[Dict[str, str]]) -> None:
        try:
            self.backup_path.parent.mkdir(parents=True, exist_ok=True)
            self.backup_path.write_text(
                json.dumps({"packages": updates}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as exc:
            self.log.warning("Не удалось сохранить %s: %s", self.backup_path, exc)

    def load_backup(self) -> List[Dict[str, str]]:
        try:
            if self.backup_path.exists():
                data = json.loads(self.backup_path.read_text(encoding="utf-8-sig"))
                return list(data.get("packages", []))
        except Exception as exc:
            self.log.debug("Не удалось прочитать %s: %s", self.backup_path, exc)
        return []

    def upgrade_all(self) -> bool:
        """Выполняет winget upgrade --all."""
        try:
            result = shell.run([
                "winget", "upgrade", "--all", "--include-unknown",
                "--accept-source-agreements", "--accept-package-agreements",
                "--disable-interactivity",
            ], timeout=3600)
            ok = result.returncode == 0
            self.log.info("winget upgrade --all: %s.", "успешно" if ok else f"код {result.returncode}")
            return ok
        except Exception as exc:
            self.log.warning("Ошибка winget upgrade --all: %s", exc)
            return False

    def rollback(self) -> List[str]:
        """Возвращает прежние версии пакетов из резервного файла."""
        restored: List[str] = []
        for item in self.load_backup():
            package_id = item.get("id")
            version = item.get("current")
            if not package_id or not version:
                continue
            try:
                result = shell.run([
                    "winget", "install", "--id", package_id, "--version", version,
                    "--accept-source-agreements", "--accept-package-agreements",
                    "--disable-interactivity",
                ], timeout=1800)
                if result.returncode == 0:
                    restored.append(package_id)
                    self.log.info("Пакет %s возвращён к версии %s.", package_id, version)
            except Exception as exc:
                self.log.warning("Не удалось вернуть %s: %s", package_id, exc)
        return restored

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        """Проверка (и, при разрешении, установка) обновлений."""
        report: dict = {"available": [], "updated": False, "count": 0}
        try:
            if not getattr(self.config, "winget_enabled", False):
                self.log.info("Модуль обновлений winget выключен в конфигурации — пропуск.")
                return report

            updates = self.available()
            report["available"] = updates
            report["count"] = len(updates)

            if updates and getattr(self.config, "winget_upgrade_all", False):
                self._save_backup(updates)
                report["updated"] = self.upgrade_all()
        except Exception as exc:
            self.log.exception("Неожиданная ошибка WingetUpdater.run: %s", exc)
        return report

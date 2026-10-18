"""Очистка мусора: временные файлы, корзина, старые логи.

Модуль сознательно «осторожен»: перед удалением содержимого каталога
проверяется, что каталог не является корнем диска, системным или личным
каталогом пользователя. Правила защиты вынесены в общий модуль `safety`,
поэтому они одинаковы во всех модулях программы.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import List, Tuple

from ..core.system import safety, shell
from ..core.logger import get_logger

log = get_logger("cleaner")


class Cleaner:
    """Удаляет временные файлы, очищает корзину и ротированные логи."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log

    # ------------------------------------------------------------------ #
    # Вспомогательные проверки
    # ------------------------------------------------------------------ #
    def _expand_path(self, path: str) -> Path:
        """Раскрывает переменные окружения в пути (например, %TEMP%)."""
        return Path(os.path.expandvars(path))

    @staticmethod
    def _count_files(path: Path) -> int:
        """Рекурсивно считает количество файлов внутри каталога."""
        try:
            return sum(1 for f in path.rglob("*") if f.is_file())
        except Exception:
            return 0

    @staticmethod
    def _normalize(path) -> str:
        """Нормализует путь для сравнения (делегат в safety)."""
        return safety.normalize(path)

    def _is_protected(self, path: Path) -> bool:
        """True, если каталог удалять нельзя (делегат в safety)."""
        return safety.is_protected(path)

    @staticmethod
    def _is_junction(path: Path) -> bool:
        """Проверяет, является ли путь junction-ссылкой (Windows)."""
        checker = getattr(os.path, "isjunction", None)
        if checker is None:  # pragma: no cover - Python < 3.12
            return False
        try:
            return bool(checker(path))
        except OSError:
            return False

    @staticmethod
    def _make_writable(path) -> None:
        """Снимает атрибут «только чтение», мешающий удалению."""
        try:
            os.chmod(path, stat.S_IWRITE)
        except Exception:
            pass

    def _remove_file(self, path: Path) -> bool:
        """Удаляет файл, при необходимости снимая атрибут «только чтение»."""
        try:
            path.unlink()
            return True
        except Exception:
            self._make_writable(path)
            try:
                path.unlink()
                return True
            except Exception as exc:
                self.log.debug("Не удалось удалить файл %s: %s", path, exc)
                return False

    def _rmtree(self, path: Path) -> bool:
        """Удаляет каталог целиком; возвращает True, только если он исчез."""
        def handle(func, target, exc) -> None:
            self._make_writable(target)
            try:
                func(target)
            except Exception as exc2:
                self.log.debug("Не удалось удалить %s: %s", target, exc2)

        try:
            try:
                shutil.rmtree(path, onexc=handle)  # Python 3.12+
            except TypeError:  # pragma: no cover - старые версии Python
                shutil.rmtree(path, onerror=lambda f, p, info: handle(f, p, info[1]))
        except Exception as exc:
            self.log.debug("Ошибка удаления каталога %s: %s", path, exc)
        return not path.exists()

    # ------------------------------------------------------------------ #
    # Временные файлы
    # ------------------------------------------------------------------ #
    def clean_temp(self, paths: List[str] | None = None) -> Tuple[int, int]:
        """Удаляет файлы и подкаталоги в переданных временных каталогах.

        Каталоги из защитного списка (корни дисков, C:\\Windows, профиль
        пользователя и т.п.) пропускаются с предупреждением.
        Ссылки и junction-каталоги удаляются как ссылки — их содержимое
        (возможно, находящееся вне temp) не затрагивается.

        Returns:
            (число_удалённых_файлов, число_удалённых_каталогов)
        """
        removed_files = 0
        removed_dirs = 0
        targets = paths if paths is not None else self.config.temp_paths

        for raw_path in targets:
            try:
                root = self._expand_path(raw_path)
                if not root.exists() or not root.is_dir():
                    self.log.trace("Каталог не найден, пропуск: %s", root)
                    continue

                if self._is_protected(root):
                    self.log.warning("Каталог %s защищён — очистка пропущена.", root)
                    continue

                for entry in root.iterdir():
                    try:
                        # Символическая ссылка: удаляем только саму ссылку.
                        if entry.is_symlink():
                            if self._remove_file(entry):
                                removed_files += 1
                            continue

                        # Junction: удаляем ссылку, не заходя внутрь.
                        if self._is_junction(entry):
                            try:
                                entry.rmdir()
                                removed_dirs += 1
                                self.log.trace("Удалена junction-ссылка: %s", entry)
                            except Exception as exc:
                                self.log.debug("Не удалось удалить junction %s: %s", entry, exc)
                            continue

                        if entry.is_file():
                            if self._remove_file(entry):
                                removed_files += 1
                            continue

                        if entry.is_dir():
                            inner_files = self._count_files(entry)
                            if self._rmtree(entry):
                                removed_files += inner_files
                                removed_dirs += 1
                                self.log.trace("Удалён каталог: %s", entry)
                            else:
                                # Удалено частично (занятые файлы) — считаем разницу.
                                remaining = self._count_files(entry)
                                removed_files += max(0, inner_files - remaining)
                                self.log.debug("Каталог удалён частично: %s", entry)
                    except Exception as exc:  # занят/нет прав — пропускаем
                        self.log.debug("Не удалось удалить %s: %s", entry, exc)
            except Exception as exc:
                self.log.warning("Ошибка обработки каталога %s: %s", raw_path, exc)

        self.log.info("Очистка временных файлов завершена: файлов=%d, каталогов=%d.",
                      removed_files, removed_dirs)
        return removed_files, removed_dirs

    # ------------------------------------------------------------------ #
    # Корзина
    # ------------------------------------------------------------------ #
    def empty_recycle_bin(self) -> bool:
        """Очищает корзину через PowerShell (Clear-RecycleBin).

        Пустая корзина — не ошибка: команда завершается кодом 0.
        """
        try:
            command = (
                "Clear-RecycleBin -Force -Confirm:$false "
                "-ErrorAction SilentlyContinue; exit 0"
            )
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
            result = shell.run(cmd, timeout=120)
            stderr = (result.stderr or "").strip()
            if stderr:
                self.log.debug("Clear-RecycleBin: %s", stderr)

            if result.returncode == 0:
                self.log.info("Корзина очищена.")
                return True
            self.log.warning("Очистка корзины вернула код %s: %s", result.returncode, stderr)
            return False
        except Exception as exc:
            self.log.warning("Ошибка очистки корзины: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Старые логи
    # ------------------------------------------------------------------ #
    def clean_old_logs(self, log_dir: str = "logs", retention_days: int | None = None) -> int:
        """Удаляет файлы журнала старше retention_days дней (кроме открытого app.log).

        Returns:
            число удалённых файлов.
        """
        removed = 0
        try:
            retention = retention_days if retention_days is not None else self.config.log_retention_days
            if retention <= 0:
                return 0

            log_path = Path(log_dir)
            if not log_path.is_dir():
                return 0

            cutoff = time.time() - retention * 86400
            for f in log_path.glob("app.log*"):
                try:
                    if f.name == "app.log":
                        continue  # текущий открытый файл не трогаем
                    if f.is_file() and f.stat().st_mtime < cutoff:
                        if self._remove_file(f):
                            removed += 1
                            self.log.trace("Удалён старый лог: %s", f)
                except Exception as exc:
                    self.log.debug("Не удалось удалить лог %s: %s", f, exc)

            self.log.info("Удалено старых лог-файлов: %d.", removed)
        except Exception as exc:
            self.log.warning("Ошибка очистки старых логов: %s", exc)
        return removed

    # ------------------------------------------------------------------ #
    # Сводный запуск
    # ------------------------------------------------------------------ #
    def run_all(self) -> dict:
        """Выполняет все этапы очистки и возвращает отчёт-словарь."""
        report = {"temp_files_removed": 0, "temp_dirs_removed": 0,
                  "recycle_bin_cleaned": False, "old_logs_removed": 0}

        try:
            files, dirs = self.clean_temp()
            report["temp_files_removed"] = files
            report["temp_dirs_removed"] = dirs
        except Exception as exc:
            self.log.exception("Неожиданная ошибка clean_temp: %s", exc)

        try:
            if self.config.clean_recycle_bin:
                report["recycle_bin_cleaned"] = self.empty_recycle_bin()
        except Exception as exc:
            self.log.exception("Неожиданная ошибка empty_recycle_bin: %s", exc)

        try:
            report["old_logs_removed"] = self.clean_old_logs(self.config.log_dir)
        except Exception as exc:
            self.log.exception("Неожиданная ошибка clean_old_logs: %s", exc)

        return report

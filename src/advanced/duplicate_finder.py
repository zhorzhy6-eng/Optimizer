"""Поиск больших файлов и дубликатов.

Безопасность:
- сканируются только каталоги из `duplicates.scan_paths`, причём защищённые
  (системные, личные) отбрасываются модулем `safety`;
- по умолчанию модуль выключен и удаление запрещено — формируется только отчёт;
- удаление (при `delete_duplicates: true`) выполняется лишь внутри разрешённых
  каталогов и всегда оставляет самую старую копию;
- число просматриваемых файлов ограничено `max_files`.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, List

from ..core.system import safety
from ..core.logger import get_logger

log = get_logger("duplicate_finder")

_CHUNK = 1024 * 1024  # 1 МБ
_PARTIAL = 64 * 1024  # первые 64 КБ для быстрой отбраковки


class DuplicateFinder:
    """Находит большие файлы и дубликаты по содержимому."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log

    # ------------------------------------------------------------------ #
    def _scan_roots(self) -> List[str]:
        raw_paths = [os.path.expandvars(str(p)) for p in getattr(self.config, "duplicates_scan_paths", [])]
        return safety.filter_safe_paths(raw_paths)

    def _collect(self, roots: List[str], min_size: int, max_files: int) -> List[Dict[str, object]]:
        files: List[Dict[str, object]] = []
        for root in roots:
            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    # Не уходим в защищённые каталоги и ссылки.
                    dirnames[:] = [
                        d for d in dirnames
                        if not os.path.islink(os.path.join(dirpath, d))
                        and not safety.is_protected(os.path.join(dirpath, d))
                    ]
                    for name in filenames:
                        if len(files) >= max_files:
                            self.log.warning("Достигнут лимит файлов (%d) — сканирование остановлено.", max_files)
                            return files
                        path = Path(dirpath) / name
                        try:
                            if path.is_symlink() or not path.is_file():
                                continue
                            stat = path.stat()
                            if stat.st_size < min_size:
                                continue
                            files.append({
                                "path": str(path),
                                "size": int(stat.st_size),
                                "mtime": float(stat.st_mtime),
                            })
                        except (OSError, PermissionError):
                            continue
            except Exception as exc:
                self.log.warning("Ошибка обхода %s: %s", root, exc)
        return files

    @staticmethod
    def _hash(path: str, partial: bool = False) -> str:
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                remaining = _PARTIAL if partial else None
                while True:
                    chunk = handle.read(_CHUNK if remaining is None else min(_CHUNK, remaining))
                    if not chunk:
                        break
                    digest.update(chunk)
                    if remaining is not None:
                        remaining -= len(chunk)
                        if remaining <= 0:
                            break
        except (OSError, PermissionError):
            return ""
        return digest.hexdigest()

    def find_duplicates(self, files: List[Dict[str, object]]) -> List[List[Dict[str, object]]]:
        """Группы файлов с одинаковым содержимым."""
        by_size: Dict[int, List[Dict[str, object]]] = {}
        for item in files:
            by_size.setdefault(int(item["size"]), []).append(item)

        groups: List[List[Dict[str, object]]] = []
        for size, items in by_size.items():
            if len(items) < 2:
                continue
            by_partial: Dict[str, List[Dict[str, object]]] = {}
            for item in items:
                key = self._hash(str(item["path"]), partial=True)
                if key:
                    by_partial.setdefault(key, []).append(item)

            for candidates in by_partial.values():
                if len(candidates) < 2:
                    continue
                by_full: Dict[str, List[Dict[str, object]]] = {}
                for item in candidates:
                    key = self._hash(str(item["path"]))
                    if key:
                        by_full.setdefault(key, []).append(item)
                groups.extend(group for group in by_full.values() if len(group) > 1)
        return groups

    def delete_duplicates(self, groups: List[List[Dict[str, object]]], roots: List[str]) -> Dict[str, object]:
        """Удаляет дубликаты, оставляя самую старую копию в каждой группе."""
        deleted: List[str] = []
        freed = 0
        for group in groups:
            ordered = sorted(group, key=lambda item: float(item["mtime"]))
            for item in ordered[1:]:
                path = str(item["path"])
                resolved = safety.resolve_under(path, roots)
                if resolved is None:
                    self.log.warning("Файл %s вне разрешённых каталогов — удаление пропущено.", path)
                    continue
                try:
                    size = int(item["size"])
                    os.remove(resolved)
                    deleted.append(path)
                    freed += size
                    self.log.info("Удалён дубликат: %s", path)
                except Exception as exc:
                    self.log.warning("Не удалось удалить %s: %s", path, exc)
        return {"deleted": deleted, "freed_mb": round(freed / 1024 ** 2, 1)}

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        """Сканирует каталоги, находит большие файлы и дубликаты."""
        report: dict = {"scanned": 0, "large_files": [], "duplicate_groups": 0,
                        "duplicate_files": 0, "deleted": [], "freed_mb": 0.0, "errors": []}
        try:
            if not getattr(self.config, "duplicates_enabled", False):
                self.log.info("Поиск дубликатов выключен в конфигурации — пропуск.")
                return report

            roots = self._scan_roots()
            if not roots:
                self.log.info("Каталоги для сканирования не заданы — пропуск.")
                return report

            min_size = int(float(getattr(self.config, "duplicates_min_size_mb", 10.0)) * 1024 ** 2)
            max_files = int(getattr(self.config, "duplicates_max_files", 20000) or 20000)

            files = self._collect(roots, min_size, max_files)
            report["scanned"] = len(files)
            report["large_files"] = [
                {"path": item["path"], "size_mb": round(int(item["size"]) / 1024 ** 2, 1)}
                for item in sorted(files, key=lambda i: int(i["size"]), reverse=True)[:10]
            ]

            if getattr(self.config, "duplicates_find", True):
                groups = self.find_duplicates(files)
                report["duplicate_groups"] = len(groups)
                report["duplicate_files"] = sum(len(group) - 1 for group in groups)

                if getattr(self.config, "duplicates_delete", False) and groups:
                    outcome = self.delete_duplicates(groups, roots)
                    report["deleted"] = outcome["deleted"]
                    report["freed_mb"] = outcome["freed_mb"]
                elif groups:
                    self.log.info("Найдено групп дубликатов: %d (удаление выключено).", len(groups))

            self.log.info("Сканирование завершено: файлов=%d, групп дубликатов=%d, освобождено=%.1f МБ.",
                          report["scanned"], report["duplicate_groups"], report["freed_mb"])
        except Exception as exc:
            self.log.exception("Неожиданная ошибка DuplicateFinder.run: %s", exc)
            report["errors"].append(str(exc))
        return report

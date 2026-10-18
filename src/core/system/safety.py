"""Общие правила безопасности для операций с файловой системой.

Используется модулями очистки, поиска дубликатов и любыми другими, которые
работают с путями пользователя. Единое место гарантирует, что защита
(корни дисков, системные и личные каталоги) одинакова везде.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional, Set

from ..logger import get_logger

log = get_logger("safety")

# Каталоги из переменных окружения, которые нельзя изменять никогда.
PROTECTED_ENV_VARS = (
    "SystemRoot",
    "windir",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PUBLIC",
)

# Личные папки внутри профиля пользователя.
PERSONAL_DIRS = (
    "Documents", "Desktop", "Downloads", "Pictures", "Videos", "Music", "OneDrive",
)


def normalize(path) -> str:
    """Нормализует путь для сравнения: абсолютный, без хвостового слэша."""
    try:
        text = os.path.normcase(os.path.normpath(os.path.abspath(str(path))))
    except Exception:
        return str(path).lower()
    return text.rstrip("\\/") or text


def protected_paths() -> Set[str]:
    """Набор путей, которые запрещено изменять."""
    protected: Set[str] = set()
    for var in PROTECTED_ENV_VARS:
        value = os.environ.get(var)
        if value:
            protected.add(normalize(value))
    home = os.environ.get("USERPROFILE")
    if home:
        for name in PERSONAL_DIRS:
            protected.add(normalize(os.path.join(home, name)))
    return protected


def is_protected(path) -> bool:
    """True, если каталог трогать нельзя (корень диска, системный, личный).

    При любой неопределённости возвращает True — лучше пропустить операцию,
    чем удалить лишнее.
    """
    try:
        resolved = Path(os.path.abspath(str(path)))
    except Exception:
        return True

    # Корень диска: C:\, D:\ ...
    if resolved.parent == resolved:
        return True

    candidate = normalize(resolved)
    protected = protected_paths()
    if candidate in protected:
        return True

    # Каталог-«родитель» защищённого тоже нельзя трогать (например, C:\Users).
    for item in protected:
        if item.startswith(candidate + os.sep):
            return True
    return False


def is_within(path, roots: Iterable[str]) -> bool:
    """True, если путь находится внутри одного из разрешённых корней."""
    candidate = normalize(path)
    for root in roots:
        try:
            root_norm = normalize(root)
        except Exception:
            continue
        if candidate == root_norm or candidate.startswith(root_norm + os.sep):
            return True
    return False


def filter_safe_paths(paths: Iterable[str]) -> List[str]:
    """Оставляет только те каталоги, которые существуют и не защищены."""
    result: List[str] = []
    for raw in paths:
        expanded = os.path.expandvars(str(raw))
        path = Path(expanded)
        if not path.exists() or not path.is_dir():
            log.warning("Каталог не найден, пропуск: %s", path)
            continue
        if is_protected(path):
            log.warning("Каталог %s защищён — пропуск.", path)
            continue
        result.append(str(path))
    return result


def resolve_under(path, roots: Iterable[str]) -> Optional[Path]:
    """Возвращает путь, если он существует, не защищён и лежит внутри roots."""
    try:
        candidate = Path(os.path.abspath(str(path)))
    except Exception:
        return None
    if is_protected(candidate):
        return None
    if roots and not is_within(candidate, roots):
        return None
    return candidate

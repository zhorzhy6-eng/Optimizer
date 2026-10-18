"""Системные вызовы Windows: права администратора, простой, кодовые страницы.

Вынесено отдельно, чтобы ctypes-логика не дублировалась в модулях
(раньше она была в main.py, shell.py и process_monitor.py).
"""
from __future__ import annotations

import ctypes
import os
import sys
from typing import Optional

from ..logger import get_logger

log = get_logger("system")


def is_windows() -> bool:
    """True, если программа запущена под Windows."""
    return os.name == "nt"


def is_admin() -> bool:
    """Проверяет права администратора.

    Возвращает False вне Windows и при любой ошибке вызова.
    """
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:
        log.debug("Не удалось определить права администратора: %s", exc)
        return False


def idle_seconds() -> float:
    """Возвращает время (сек) с последнего ввода пользователя.

    Windows-реализация на GetLastInputInfo. Возвращает 0.0 вне Windows
    и при ошибке (0.0 означает «пользователь активен» — безопасно).
    """
    if not is_windows():
        return 0.0
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0

        # dwTime — младшие 32 бита счётчика тиков, поэтому сравниваем с
        # младшими 32 битами GetTickCount64: иначе после ~49.7 дней аптайма
        # разница становится отрицательной.
        kernel32 = ctypes.windll.kernel32
        kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        now_ms = int(kernel32.GetTickCount64())
        diff = (now_ms & 0xFFFFFFFF) - int(lii.dwTime)
        if diff < 0:
            diff += 1 << 32
        return max(0.0, diff / 1000.0)
    except Exception as exc:
        log.warning("Не удалось определить idle-время: %s", exc)
        return 0.0


def codepage(kind: str = "oem") -> Optional[int]:
    """Кодовая страница Windows: 'oem' (консоль) или 'ansi'.

    Возвращает None вне Windows или при ошибке.
    """
    if not is_windows():
        return None
    try:
        if kind == "oem":
            return int(ctypes.windll.kernel32.GetOEMCP())
        return int(ctypes.windll.kernel32.GetACP())
    except Exception as exc:
        log.debug("Не удалось получить кодовую страницу (%s): %s", kind, exc)
        return None

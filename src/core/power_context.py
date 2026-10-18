"""Состояние фонового агента питания: logs/power_context.json.

Хранит текущий контекст, применённую схему и историю переключений.
Запись атомарная: временный файл + os.replace, поэтому при внезапном
завершении агента файл не остаётся повреждённым.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Union

from .constants import DEFAULT_LOG_DIR
from .logger import get_logger

log = get_logger("power_context")

CONTEXT_FILE = "power_context.json"
HISTORY_LIMIT = 20


def context_path(log_dir: Union[str, Path] = DEFAULT_LOG_DIR) -> Path:
    """Путь к файлу состояния агента."""
    return Path(log_dir) / CONTEXT_FILE


def load(log_dir: Union[str, Path] = DEFAULT_LOG_DIR) -> dict:
    """Читает сохранённое состояние (пустой словарь, если файла нет)."""
    path = context_path(log_dir)
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log.warning("Не удалось прочитать %s: %s", path, exc)
        return {}


def save(state: dict, log_dir: Union[str, Path] = DEFAULT_LOG_DIR) -> bool:
    """Атомарно сохраняет состояние: временный файл + os.replace."""
    path = context_path(log_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, path)
        return True
    except Exception as exc:
        log.warning("Не удалось сохранить %s: %s", path, exc)
        return False


def update(state: dict, context: str, scheme: str, now: float) -> dict:
    """Формирует новое состояние после переключения контекста.

    Args:
        state: предыдущее состояние (или {} при первом запуске).
        context: новый контекст ("game", "heavy", "office", "idle").
        scheme: имя применённой схемы питания.
        now: текущее время (time.time()).

    Returns:
        Новый словарь состояния с историей (последние HISTORY_LIMIT записей).
    """
    history = state.get("history", [])
    if not isinstance(history, list):
        history = []
    history.append({"context": context, "scheme": scheme, "at": now})
    history = history[-HISTORY_LIMIT:]

    minute_ago = now - 60.0
    switches_last_minute = sum(
        1 for item in history
        if isinstance(item, dict)
        and isinstance(item.get("at"), (int, float))
        and float(item["at"]) >= minute_ago
    )
    return {
        "current": context,
        "scheme": scheme,
        "since": now,
        "last_switch": now,
        "switches_last_minute": switches_last_minute,
        "history": history,
    }

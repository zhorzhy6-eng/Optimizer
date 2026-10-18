"""Состояние последнего успешного запуска (logs/state.json).

Файл нужен для догоняющего запуска: если ПК был выключен или спал в
запланированное время, при следующем старте программа видит пропуск
и выполняет соответствующую задачу.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional, Union

from .constants import STATE_FILE_NAME
from .logger import get_logger

log = get_logger("state")

STATE_FILE = STATE_FILE_NAME  # обратная совместимость с прежним именем в main


def load_state(state_path: Union[str, Path]) -> Optional[dt.datetime]:
    """Читает время последнего успешного запуска (None, если данных нет)."""
    try:
        path = Path(state_path)
        if not path.exists():
            return None
        # utf-8-sig устойчив к BOM, который может добавить внешний редактор.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        raw = data.get("last_run")
        return dt.datetime.fromisoformat(raw) if raw else None
    except Exception as exc:
        log.debug("Не удалось прочитать %s: %s", state_path, exc)
        return None


def save_state(state_path: Union[str, Path], moment: Optional[dt.datetime] = None) -> None:
    """Сохраняет время последнего успешного запуска."""
    try:
        path = Path(state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        moment = moment or dt.datetime.now()
        path.write_text(
            json.dumps({"last_run": moment.isoformat()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("Не удалось сохранить state.json: %s", exc)

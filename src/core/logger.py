"""Настройка логирования для PC Optimizer Pro.

Единый файл лога: logs/app.log.
Каждый модуль получает свой логгер через get_logger("<имя>").
Дополнительно к стандартным уровням добавлен уровень TRACE (ниже DEBUG)
для детальной отладки.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

TRACE_LEVEL = 5
_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Регистрируем TRACE-уровень и метод Logger.trace один раз.
if not hasattr(logging, "TRACE"):
    logging.TRACE = TRACE_LEVEL  # type: ignore[attr-defined]
    logging.addLevelName(TRACE_LEVEL, "TRACE")


def _trace(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)


if not hasattr(logging.Logger, "trace"):
    logging.Logger.trace = _trace  # type: ignore[attr-defined]

_CONFIGURED = False


def setup_logging(
    log_dir: str | Path = "logs",
    console: bool = False,
    level: int | str = TRACE_LEVEL,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """Настраивает корневой логгер (идемпотентно) и возвращает его.

    Args:
        log_dir: каталог, куда пишется app.log.
        console: дублировать вывод в stdout.
        level: уровень логирования (int или строка, напр. "TRACE").
        max_bytes: размер файла до ротации.
        backup_count: сколько ротированных файлов хранить.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return logging.getLogger()

    try:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"

        if isinstance(level, str):
            level = _level_from_name(level)

        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        root = logging.getLogger()
        root.setLevel(level)

        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,  # файл открывается при первой записи — меньше конфликтов
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        if console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)

        _CONFIGURED = True
    except Exception as exc:  # логирование не должно ронять программу
        # Аварийный вывод в stderr, если файл лога создать не удалось.
        print(f"Ошибка настройки логирования: {exc}", file=sys.stderr)

    return logging.getLogger()


def _level_from_name(name: str) -> int:
    """Возвращает числовой уровень по строковому имени (в т.ч. TRACE)."""
    normalized = name.upper().strip()
    if normalized == "TRACE":
        return TRACE_LEVEL
    return getattr(logging, normalized, TRACE_LEVEL)


def get_logger(name: str) -> logging.Logger:
    """Возвращает именованный логгер (используется каждым модулем)."""
    return logging.getLogger(f"pc_optimizer.{name}")


def reset_logging_state() -> None:
    """Сбрасывает флаг настройки и закрывает хендлеры (нужно только для тестов)."""
    global _CONFIGURED
    _CONFIGURED = False
    root = logging.getLogger()
    for handler in list(root.handlers):
        try:
            handler.close()
        except Exception:
            pass
        root.removeHandler(handler)

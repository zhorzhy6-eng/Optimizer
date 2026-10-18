"""Общие константы проекта.

Единое место для имён, которые иначе дублируются в Python-коде,
PowerShell-скриптах и bat-файлах.
"""
from __future__ import annotations

APP_NAME = "PC Optimizer Pro"

# Имена задач в Планировщике заданий Windows.
TASK_NAME_LIGHT = f"{APP_NAME} (Light)"
TASK_NAME_FULL = f"{APP_NAME} (Full)"
LEGACY_TASK_NAME = APP_NAME  # задача старого формата (до разделения light/full)
ALL_TASK_NAMES = (TASK_NAME_LIGHT, TASK_NAME_FULL, LEGACY_TASK_NAME)

# Пути по умолчанию (относительно корня проекта).
DEFAULT_CONFIG_PATH = "config/settings.yaml"
DEFAULT_LOG_DIR = "logs"
STATE_FILE_NAME = "state.json"
REPORT_PREFIX = "report_"

# Режимы запуска.
MODE_LIGHT = "light"
MODE_FULL = "full"

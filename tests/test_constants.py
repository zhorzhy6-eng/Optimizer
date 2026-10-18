"""Тесты констант проекта (src/core/constants.py)."""
from __future__ import annotations

from src.core import constants


def test_app_name():
    assert constants.APP_NAME == "PC Optimizer Pro"


def test_task_names_match_scheduler_naming():
    assert constants.TASK_NAME_LIGHT == "PC Optimizer Pro (Light)"
    assert constants.TASK_NAME_FULL == "PC Optimizer Pro (Full)"
    assert constants.LEGACY_TASK_NAME == "PC Optimizer Pro"
    assert set(constants.ALL_TASK_NAMES) == {
        constants.TASK_NAME_LIGHT, constants.TASK_NAME_FULL, constants.LEGACY_TASK_NAME,
    }


def test_default_paths():
    assert constants.DEFAULT_CONFIG_PATH == "config/settings.yaml"
    assert constants.DEFAULT_LOG_DIR == "logs"
    assert constants.STATE_FILE_NAME == "state.json"
    assert constants.MODE_LIGHT == "light"
    assert constants.MODE_FULL == "full"


def test_task_names_used_by_powershell_scripts():
    """Имена задач в .ps1 должны совпадать с константами (регресс-защита)."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    script = (root / "install_scheduled_task.ps1").read_text(encoding="utf-8-sig")
    assert constants.TASK_NAME_LIGHT in script
    assert constants.TASK_NAME_FULL in script

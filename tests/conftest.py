"""Фикстуры pytest для PC Optimizer Pro."""
from __future__ import annotations

import logging

import pytest

from src.core.config import Config
from src.core.logger import reset_logging_state


@pytest.fixture(autouse=True)
def _silent_logging():
    """Гасит вывод логов в тестах (уровень CRITICAL), не трогая файлы."""
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)
    reset_logging_state()


@pytest.fixture
def config() -> Config:
    """Базовая конфигурация для тестов."""
    return Config()

"""Тесты обёртки состояния агента питания (src/core/power_context.py)."""
from __future__ import annotations

import json

from src.core import power_context


def test_save_and_load_roundtrip(tmp_path):
    state = power_context.update({}, "idle", "power_saver", 1758870000.0)
    assert power_context.save(state, str(tmp_path)) is True
    assert (tmp_path / "power_context.json").exists()

    loaded = power_context.load(str(tmp_path))
    assert loaded["current"] == "idle"
    assert loaded["scheme"] == "power_saver"
    assert loaded["history"][-1]["at"] == 1758870000.0


def test_load_missing_file(tmp_path):
    assert power_context.load(str(tmp_path)) == {}


def test_load_corrupted_file(tmp_path):
    path = tmp_path / "power_context.json"
    path.write_text("{не json", encoding="utf-8")
    assert power_context.load(str(tmp_path)) == {}


def test_history_limited_to_20(tmp_path):
    state = {}
    for index in range(30):
        state = power_context.update(state, "idle", "power_saver", 1758870000.0 + index)
    assert len(state["history"]) == 20
    assert state["history"][-1]["at"] == 1758870000.0 + 29


def test_switches_last_minute_counted(tmp_path):
    state = {}
    now = 1758870000.0
    for offset in range(5):
        state = power_context.update(state, "idle", "power_saver", now - 50 + offset)
    assert state["switches_last_minute"] == 5

    # старые переключения не считаются
    state2 = power_context.update(state, "game", "high_performance", now + 100)
    assert state2["switches_last_minute"] == 1


def test_update_keeps_since_and_last_switch(tmp_path):
    state = power_context.update({}, "idle", "power_saver", 100.0)
    assert state["since"] == 100.0
    assert state["last_switch"] == 100.0


def test_atomic_save_no_tmp_left(tmp_path):
    power_context.save({"current": "idle"}, str(tmp_path))
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []

    # и сам файл — валидный JSON
    data = json.loads((tmp_path / "power_context.json").read_text(encoding="utf-8"))
    assert data["current"] == "idle"

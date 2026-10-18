"""Тесты состояния последнего запуска (src/state.py)."""
from __future__ import annotations

import datetime as dt

from src.core.state import STATE_FILE, load_state, save_state


def test_state_file_name():
    assert STATE_FILE == "state.json"


def test_load_missing_file(tmp_path):
    assert load_state(tmp_path / "state.json") is None


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    moment = dt.datetime(2026, 9, 25, 14, 30, 15)
    save_state(path, moment)

    assert path.exists()
    assert load_state(path) == moment


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "state.json"
    save_state(path, dt.datetime(2026, 1, 1, 12, 0))
    assert path.exists()


def test_load_corrupted_file_returns_none(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{не json", encoding="utf-8")
    assert load_state(path) is None


def test_load_ignores_bom(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"last_run": "2026-09-25T10:00:00"}', encoding="utf-8-sig")
    assert load_state(path) == dt.datetime(2026, 9, 25, 10, 0)


def test_load_without_last_run_key(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"other": 1}', encoding="utf-8")
    assert load_state(path) is None

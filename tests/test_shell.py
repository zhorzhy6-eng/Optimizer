"""Тесты обёртки запуска консольных утилит (src/core/system/shell.py)."""
from __future__ import annotations

import pytest

from src.core.system import shell

RUSSIAN = "Существующие схемы управления питанием (* - активные)"


class _FakeCompleted:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.args = ["fake"]
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# --------------------------------------------------------------------- #
# Декодирование вывода
# --------------------------------------------------------------------- #
def test_decode_utf8():
    assert shell.decode_output(RUSSIAN.encode("utf-8")) == RUSSIAN


def test_decode_cp866():
    assert shell.decode_output(RUSSIAN.encode("cp866")) == RUSSIAN


def test_decode_cp1251():
    assert shell.decode_output(RUSSIAN.encode("cp1251")) == RUSSIAN


def test_decode_ascii_mixed():
    data = b"Published Name: oem49.inf"
    assert shell.decode_output(data) == "Published Name: oem49.inf"


def test_decode_empty_and_none():
    assert shell.decode_output(b"") == ""
    assert shell.decode_output(None) == ""


def test_decode_forced_encoding():
    assert shell.decode_output(RUSSIAN.encode("cp866"), encoding="cp866") == RUSSIAN
    # при неверной принудительной кодировке не падает
    assert shell.decode_output(RUSSIAN.encode("cp866"), encoding="ascii") != ""


def test_candidate_encodings_order_and_uniqueness():
    encodings = shell.candidate_encodings()
    assert encodings[0] == "utf-8"
    assert len(encodings) == len(set(encodings))
    assert all(enc.startswith("cp") or enc == "utf-8" for enc in encodings)


def test_readability_prefers_clean_text():
    clean = shell._readability("Схемы питания")
    garbled = shell._readability("╨б╤Е╨╡╨╝╤Л")
    assert clean > garbled


# --------------------------------------------------------------------- #
# run()
# --------------------------------------------------------------------- #
def test_run_decodes_bytes(monkeypatch):
    monkeypatch.setattr(
        "src.core.system.shell.subprocess.run",
        lambda *a, **k: _FakeCompleted(stdout=RUSSIAN.encode("utf-8")),
    )
    result = shell.run(["powercfg", "/list"])
    assert result.returncode == 0
    assert result.stdout == RUSSIAN
    assert result.stderr == ""


def test_run_accepts_text_from_mock(monkeypatch):
    """Мок, возвращающий строки вместо байтов, тоже поддерживается."""
    monkeypatch.setattr(
        "src.core.system.shell.subprocess.run",
        lambda *a, **k: _FakeCompleted(stdout="готово", stderr=""),
    )
    result = shell.run(["x"])
    assert result.stdout == "готово"


def test_run_passes_timeout_and_returns_completed_process(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["timeout"] = kwargs.get("timeout")
        return _FakeCompleted(stdout=b"ok")

    monkeypatch.setattr("src.core.system.shell.subprocess.run", fake_run)
    result = shell.run(["pnputil", "/enum-drivers"], timeout=42)

    assert captured["args"] == ["pnputil", "/enum-drivers"]
    assert captured["timeout"] == 42
    assert isinstance(result, shell.subprocess.CompletedProcess)
    assert result.stdout == "ok"


def test_run_propagates_timeout(monkeypatch):
    def fake_run(*a, **k):
        raise TimeoutError("timeout")

    monkeypatch.setattr("src.core.system.shell.subprocess.run", fake_run)
    with pytest.raises(TimeoutError):
        shell.run(["defrag.exe", "C:"], timeout=1)

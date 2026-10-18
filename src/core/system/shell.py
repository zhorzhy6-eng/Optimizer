"""Единая обёртка запуска консольных утилит Windows.

Проблема, которую решает модуль: консольные программы (powercfg, pnputil,
defrag, winget) выводят текст в кодировке консоли, а она зависит от
родительского процесса — UTF-8 при запуске из Windows Terminal/pwsh и
OEM-кодировка (cp866) при запуске Планировщиком заданий. Фиксированный
`text=True` в этом случае даёт «кракозябры» в логах и портит разбор вывода.

Здесь вывод читается байтами и декодируется первой подходящей кодировкой
(UTF-8 -> OEM -> ANSI), что корректно в обоих сценариях.
"""
from __future__ import annotations

import subprocess
from typing import List, Optional, Sequence

from ..logger import get_logger
from .windows import codepage as _codepage

log = get_logger("shell")

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def candidate_encodings() -> List[str]:
    """Кодировки-кандидаты в порядке приоритета."""
    encodings: List[str] = ["utf-8"]
    for kind in ("oem", "ansi"):
        cp = _codepage(kind)
        if cp:
            encodings.append(f"cp{cp}")
    encodings.append("cp1251")
    ordered: List[str] = []
    for enc in encodings:
        if enc not in ordered:
            ordered.append(enc)
    return ordered


def _readability(text: str) -> int:
    """Оценка «читаемости» текста для выбора кодировки.

    Псевдографика (box drawing) и символы замены — признак неверного
    декодирования, буквы и пробелы — признак верного.
    """
    score = 0
    for ch in text:
        code = ord(ch)
        if 0x2500 <= code <= 0x257F or code == 0xFFFD:
            score -= 5
        elif ch.isalnum() or ch.isspace():
            score += 2
        elif code > 0x7F:
            score -= 1
        else:
            score += 1
    return score


def decode_output(data: Optional[bytes], encoding: Optional[str] = None) -> str:
    """Декодирует вывод утилиты, подбирая кодировку при необходимости.

    Порядок: явная кодировка -> строгий UTF-8 (Windows Terminal, winget,
    современные утилиты) -> лучшая из однобайтовых (OEM/ANSI) по читаемости.
    """
    if not data:
        return ""
    if encoding:
        return data.decode(encoding, errors="replace")

    try:
        return data.decode("utf-8")
    except (UnicodeDecodeError, LookupError):
        pass

    best_text: Optional[str] = None
    best_score: Optional[int] = None
    for enc in candidate_encodings():
        if enc == "utf-8":
            continue
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        score = _readability(text)
        if best_score is None or score > best_score:
            best_text, best_score = text, score

    if best_text is None:
        return data.decode("utf-8", errors="replace")
    return best_text


def _as_text(value, encoding: Optional[str] = None) -> str:
    """Приводит stdout/stderr к строке (уже строка или байты)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return decode_output(value, encoding)


def run(
    args: Sequence[str],
    timeout: int = 300,
    encoding: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Запускает команду и возвращает CompletedProcess с текстовым выводом.

    Args:
        args: команда со аргументами.
        timeout: ограничение времени в секундах.
        encoding: принудительная кодировка вывода (по умолчанию — автоподбор).
    """
    result = subprocess.run(
        list(args),
        capture_output=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )
    stdout = _as_text(result.stdout, encoding)
    stderr = _as_text(result.stderr, encoding)
    command = getattr(result, "args", None) or list(args)
    return subprocess.CompletedProcess(command, result.returncode, stdout, stderr)

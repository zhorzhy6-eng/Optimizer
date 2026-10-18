"""Формирование, сохранение и вывод отчётов об оптимизации.

Вынесено из main.py: точка входа отвечает за оркестрацию, а работа с
текстовыми отчётами — за этот модуль.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Optional, Union

from .constants import DEFAULT_LOG_DIR, REPORT_PREFIX
from .logger import get_logger

log = get_logger("reporting")


def safe_print(text: str) -> None:
    """Печатает текст, не падая на символах, отсутствующих в кодировке консоли."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def format_report(report: dict) -> str:
    """Преобразует отчёт-словарь в человекочитаемый текст."""
    lines = [f"Отчёт PC Optimizer Pro — {dt.datetime.now():%Y-%m-%d %H:%M:%S}", "=" * 60]

    cleaner = report.get("cleaner", {})
    lines.append("[Очистка]")
    lines.append(f"  временных файлов удалено: {cleaner.get('temp_files_removed', 0)}")
    lines.append(f"  временных каталогов удалено: {cleaner.get('temp_dirs_removed', 0)}")
    lines.append(f"  корзина очищена: {cleaner.get('recycle_bin_cleaned', False)}")
    lines.append(f"  старых логов удалено: {cleaner.get('old_logs_removed', 0)}")

    pm = report.get("process_monitor", {})
    lines.append("[Процессы]")
    lines.append(f"  запущено процессов: {pm.get('process_count', 0)}")
    heavy = pm.get("heavy_processes", [])
    lines.append(f"  тяжёлых процессов: {len(heavy)}")
    for item in heavy[:10]:
        lines.append(f"    - {item.get('name')} (PID {item.get('pid')}) "
                     f"CPU={item.get('cpu')}% RAM={item.get('ram')}%")
    lines.append(f"  закрыто нежелательных: {', '.join(pm.get('closed_processes', [])) or 'нет'}")

    lines.append("[Питание]")
    lines.append(f"  применена схема: {report.get('power', {}).get('scheme_applied', '-')}")

    lines.append("[Дефрагментация]")
    for drive, entry in report.get("defrag", {}).items():
        if isinstance(entry, dict):
            lines.append(f"  {drive}: {entry.get('media_type', '-')} — {entry.get('reason', '-')}")
        else:
            lines.append(f"  {drive}: {entry}")

    drv = report.get("drivers", {})
    lines.append("[Драйверы]")
    lines.append(f"  установлено: {', '.join(drv.get('installed', [])) or 'нет'}")
    lines.append(f"  автообновление: {drv.get('updated', False)}")

    lines.extend(_format_extra_sections(report))

    lines.append("=" * 60)
    return "\n".join(lines)


def _format_extra_sections(report: dict) -> list:
    """Секции расширенных функций — только если модуль реально выполнялся."""
    lines: list = []

    startup = report.get("startup")
    if isinstance(startup, dict):
        lines.append("[Автозагрузка]")
        lines.append(f"  записей найдено: {len(startup.get('entries', []))}")
        lines.append(f"  отключено: {', '.join(startup.get('disabled', [])) or 'нет'}")

    services = report.get("services")
    if isinstance(services, dict):
        lines.append("[Службы]")
        lines.append(f"  всего служб: {services.get('total', 0)}")
        lines.append(f"  переведено в ручной запуск: {', '.join(services.get('changed', [])) or 'нет'}")
        if services.get("skipped_protected"):
            lines.append(f"  защищённых пропущено: {', '.join(services['skipped_protected'])}")

    network = report.get("network")
    if isinstance(network, dict):
        lines.append("[Сеть]")
        lines.append(f"  DNS-кэш сброшен: {network.get('dns_flushed', False)}")
        lines.append(f"  DNS изменён: {', '.join(network.get('dns_changed', [])) or 'нет'}")
        lines.append(f"  TCP-тюнинг: {network.get('tcp_tuned', False)}")

    health = report.get("disk_health")
    if isinstance(health, dict):
        lines.append("[Здоровье дисков]")
        for disk in health.get("disks", []):
            if isinstance(disk, dict):
                lines.append(f"  {disk.get('name')}: {disk.get('media_type')} / "
                             f"{disk.get('health')} ({disk.get('size_gb')} ГБ)")
        for volume in health.get("volumes", []):
            if isinstance(volume, dict):
                lines.append(f"  {volume.get('drive')} свободно {volume.get('free_gb')} ГБ "
                             f"({volume.get('free_percent')}%)")
        for warning in health.get("warnings", []):
            lines.append(f"  ! {warning}")

    duplicates = report.get("duplicates")
    if isinstance(duplicates, dict):
        lines.append("[Дубликаты]")
        lines.append(f"  файлов просмотрено: {duplicates.get('scanned', 0)}")
        lines.append(f"  групп дубликатов: {duplicates.get('duplicate_groups', 0)}")
        lines.append(f"  удалено копий: {len(duplicates.get('deleted', []))}, "
                     f"освобождено {duplicates.get('freed_mb', 0)} МБ")
        for item in duplicates.get("large_files", [])[:5]:
            if isinstance(item, dict):
                lines.append(f"    - {item.get('size_mb')} МБ: {item.get('path')}")

    winget = report.get("winget")
    if isinstance(winget, dict):
        lines.append("[Обновления winget]")
        lines.append(f"  доступно обновлений: {winget.get('count', 0)}")
        lines.append(f"  обновление выполнено: {winget.get('updated', False)}")
        for item in winget.get("available", [])[:5]:
            if isinstance(item, dict):
                lines.append(f"    - {item.get('name')}: {item.get('current')} -> "
                             f"{item.get('available')}")

    thermal = report.get("thermal")
    if isinstance(thermal, dict):
        lines.append("[Температура]")
        lines.append(f"  максимум: {thermal.get('max_temperature', 0)} °C")
        clock = thermal.get("clock", {}) if isinstance(thermal.get("clock"), dict) else {}
        lines.append(f"  частота CPU: {clock.get('current_mhz', 0)} из "
                     f"{clock.get('max_mhz', 0)} МГц")
        lines.append(f"  троттлинг: {thermal.get('throttling', False)}")
        for warning in thermal.get("warnings", []):
            lines.append(f"  ! {warning}")

    return lines


def write_report(config, report: dict) -> Optional[Path]:
    """Пишет текстовый отчёт в каталог report_dir (если включено в конфиге)."""
    try:
        report_dir = Path(config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        name = f"{REPORT_PREFIX}{dt.datetime.now():%Y%m%d_%H%M%S}.txt"
        path = report_dir / name
        path.write_text(format_report(report), encoding="utf-8")
        log.info("Отчёт сохранён: %s", path)
        return path
    except Exception as exc:
        log.warning("Не удалось записать отчёт: %s", exc)
        return None


def find_last_report(report_dir: Union[str, Path] = DEFAULT_LOG_DIR) -> Optional[Path]:
    """Возвращает путь к самому свежему report_*.txt (или None)."""
    try:
        directory = Path(report_dir)
        if not directory.is_dir():
            return None
        files = sorted(
            directory.glob(f"{REPORT_PREFIX}*.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files[0] if files else None
    except Exception as exc:
        log.warning("Не удалось найти отчёт: %s", exc)
        return None


def print_last_report(report_dir: Union[str, Path] = DEFAULT_LOG_DIR) -> int:
    """Выводит последний отчёт в консоль. Возвращает код возврата."""
    path = find_last_report(report_dir)
    if path is None:
        safe_print("Отчёты не найдены. Сначала выполните оптимизацию (--once или --light).")
        return 1
    try:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        safe_print(f"--- {path} ---")
        safe_print(content)
        return 0
    except Exception as exc:
        safe_print(f"Не удалось прочитать отчёт {path}: {exc}")
        return 1

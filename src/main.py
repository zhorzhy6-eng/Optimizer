"""PC Optimizer Pro — точка входа.

Запуск (от имени администратора):
    python -m src.main                 # планировщик + catch-up при старте
    python -m src.main --once          # однократный прогон всех задач (full)
    python -m src.main --light         # только очистка мусора (поверхностная чистка)
    python -m src.main --mode light    # то же, что --light
    python -m src.main --once --mode full   # то же, что --once
    python -m src.main --report        # показать последний отчёт и выйти
    python -m src.main --config PATH   # свой конфигурационный файл

Программа не падает при ошибках: каждый модуль оборачивает свою работу
в try/except и пишет в logs/app.log.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .core.config import Config
from .core.constants import DEFAULT_CONFIG_PATH, DEFAULT_LOG_DIR
from .core.logger import get_logger, setup_logging
from .core.reporting import (
    find_last_report,
    format_report,
    print_last_report,
    safe_print,
    write_report,
)
from .core.scheduler import TaskScheduler, parse_time
from .core.state import STATE_FILE, load_state, save_state
from .core.system.windows import is_admin


def _scheduled_pairs(config: Config, now: Optional[dt.datetime] = None) -> List[tuple]:
    """Возвращает список (момент_запуска, режим) для уже наступивших времён."""
    now = now or dt.datetime.now()
    pairs: List[tuple] = []
    full_times = config.effective_full_times()

    for times, mode in ((config.light_times, "light"), (full_times, "full")):
        for raw in times:
            try:
                t = parse_time(raw)
                due = now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
                if due <= now:
                    pairs.append((due, mode))
            except ValueError:
                continue
    return pairs


def _missed_run_mode(
    config: Config,
    last_run: Optional[dt.datetime],
    now: Optional[dt.datetime] = None,
) -> Optional[str]:
    """Определяет режим пропущенного запуска: 'light', 'full' или None.

    Раньше догоняющий запуск всегда выполнял полный цикл, даже если была
    пропущена только поверхностная чистка.
    """
    pairs = _scheduled_pairs(config, now)
    if not pairs:
        return None
    due, mode = max(pairs, key=lambda item: item[0])
    if last_run is not None and last_run >= due:
        return None
    return mode


def extra_steps(config: Config) -> List[tuple]:
    """Дополнительные шаги оптимизации (расширенные функции).

    Каждый шаг включается только своим флагом в конфиге, поэтому поведение
    по умолчанию не меняется: выполняются лишь безопасные проверки
    (автозагрузка, здоровье дисков, температура).

    Returns:
        список кортежей (ключ_отчёта, описание, вызываемая_функция).
    """
    steps: List[tuple] = []

    if getattr(config, "startup_enabled", False):
        from .advanced.startup_manager import StartupManager
        steps.append(("startup", "анализ автозагрузки", StartupManager(config).run))

    if getattr(config, "services_enabled", False):
        from .advanced.service_manager import ServiceManager
        steps.append(("services", "анализ служб", ServiceManager(config).run))

    if getattr(config, "network_enabled", False):
        from .advanced.network_tuner import NetworkTuner
        steps.append(("network", "сетевые настройки", NetworkTuner(config).run))

    if getattr(config, "disk_health_enabled", False):
        from .advanced.disk_health import DiskHealth
        steps.append(("disk_health", "здоровье дисков", DiskHealth(config).run))

    if getattr(config, "duplicates_enabled", False):
        from .advanced.duplicate_finder import DuplicateFinder
        steps.append(("duplicates", "поиск дубликатов", DuplicateFinder(config).run))

    if getattr(config, "winget_enabled", False):
        from .advanced.winget_updater import WingetUpdater
        steps.append(("winget", "обновления winget", WingetUpdater(config).run))

    if getattr(config, "thermal_enabled", False):
        from .advanced.thermal_monitor import ThermalMonitor
        steps.append(("thermal", "температура и троттлинг", ThermalMonitor(config).run))

    return steps


def run_all_tasks(config: Config) -> dict:
    """Последовательно выполняет все модули оптимизации.

    Возвращает объединённый отчёт-словарь. Каждая секция защищена try/except,
    поэтому сбой одного модуля не останавливает остальные.
    """
    log = get_logger("main")
    from .optimization.cleaner import Cleaner
    from .optimization.process_monitor import ProcessMonitor
    from .optimization.power_manager import PowerManager
    from .optimization.defragmenter import Defragmenter
    from .optimization.driver_manager import DriverManager

    report: dict = {}
    extras = extra_steps(config)
    total = 5 + len(extras)

    # 1. Очистка мусора
    try:
        log.info("=== Шаг 1/%d: очистка мусора ===", total)
        report["cleaner"] = Cleaner(config).run_all()
    except Exception as exc:
        log.exception("Ошибка модуля очистки: %s", exc)
        report["cleaner"] = {"error": str(exc)}

    # 2. Мониторинг процессов (имена всех процессов нужны и для схемы питания)
    process_names: List[str] = []
    try:
        log.info("=== Шаг 2/%d: мониторинг процессов ===", total)
        pm = ProcessMonitor(config)
        procs = pm.list_processes()
        process_names = [p.name for p in procs]
        heavy = pm.get_heavy_processes(procs)
        report["process_monitor"] = {
            "process_count": len(procs),
            "heavy_processes": [
                {"pid": p.pid, "name": p.name, "cpu": round(p.cpu_percent, 1),
                 "ram": round(p.memory_percent, 1)} for p in heavy
            ],
            "closed_processes": pm.close_unwanted_idle(procs),
        }
    except Exception as exc:
        log.exception("Ошибка модуля мониторинга: %s", exc)
        report["process_monitor"] = {"error": str(exc)}

    # 3. Энергопотребление
    try:
        log.info("=== Шаг 3/%d: оптимизация энергопотребления ===", total)
        report["power"] = PowerManager(config).run(process_names)
    except Exception as exc:
        log.exception("Ошибка модуля питания: %s", exc)
        report["power"] = {"error": str(exc)}

    # 4. Дефрагментация
    try:
        log.info("=== Шаг 4/%d: дефрагментация ===", total)
        report["defrag"] = Defragmenter(config).run()
    except Exception as exc:
        log.exception("Ошибка модуля дефрагментации: %s", exc)
        report["defrag"] = {"error": str(exc)}

    # 5. Драйверы
    try:
        log.info("=== Шаг 5/%d: управление драйверами ===", total)
        report["drivers"] = DriverManager(config).run()
    except Exception as exc:
        log.exception("Ошибка модуля драйверов: %s", exc)
        report["drivers"] = {"error": str(exc)}

    # 6+. Расширенные функции (каждая — только если включена в конфиге)
    for index, (key, title, action) in enumerate(extras, start=6):
        try:
            log.info("=== Шаг %d/%d: %s ===", index, total, title)
            report[key] = action()
        except Exception as exc:
            log.exception("Ошибка шага «%s»: %s", title, exc)
            report[key] = {"error": str(exc)}

    log.info("=== Цикл оптимизации завершён ===")
    return report


def run_light_tasks(config: Config) -> dict:
    """Поверхностная чистка: только модуль очистки мусора.

    Питание, процессы, дефрагментация и драйверы не затрагиваются,
    state.json не обновляется (полный цикл по расписанию остаётся актуальным).
    """
    log = get_logger("main")
    from .optimization.cleaner import Cleaner

    report: dict = {}
    try:
        log.info("=== Поверхностная чистка: очистка мусора ===")
        report["cleaner"] = Cleaner(config).run_all()
    except Exception as exc:
        log.exception("Ошибка модуля очистки: %s", exc)
        report["cleaner"] = {"error": str(exc)}
    log.info("=== Поверхностная чистка завершена ===")
    return report


def run_optimization(config: Config, state_path: Path) -> dict:
    """Выполняет полный цикл оптимизации и обновляет state.json."""
    report = run_all_tasks(config)
    if config.generate_report:
        write_report(config, report)
    save_state(state_path)
    return report


def run_light_optimization(config: Config, state_path: Path | None = None) -> dict:
    """Поверхностная чистка по расписанию.

    Вызывает только очистку мусора и НЕ обновляет state.json — полный цикл
    по расписанию остаётся актуальным для догоняющего запуска.
    """
    report = run_light_tasks(config)
    if config.generate_report:
        write_report(config, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PC Optimizer Pro — автономная оптимизация ПК")
    parser.add_argument("--once", action="store_true",
                        help="выполнить один цикл оптимизации и завершиться")
    parser.add_argument("--light", action="store_true",
                        help="поверхностная чистка: только очистка мусора")
    parser.add_argument("--mode", choices=["light", "full"], default=None,
                        help="режим прогона: light (только очистка) или full (все 5 шагов)")
    parser.add_argument("--report", action="store_true",
                        help="показать последний отчёт и выйти")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                        help="путь к конфигурационному YAML-файлу")
    parser.add_argument("--log-dir", default=None,
                        help="переопределить каталог логов")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # Сначала читаем конфигурацию (она сама логирует ошибки мягко).
    config = Config.from_yaml(args.config)

    # Затем настраиваем логирование с нужными каталогом и уровнем.
    log_dir = args.log_dir or config.log_dir
    setup_logging(log_dir=log_dir, console=False, level=config.log_level)
    log = get_logger("main")

    log.info("=" * 60)
    log.info("PC Optimizer Pro — запуск (версия %s).", __version__)
    log.info("Конфигурация: %s | Логи: %s", args.config, Path(log_dir) / "app.log")

    if not is_admin():
        log.warning("Программа запущена БЕЗ прав администратора — "
                    "очистка C:\\Windows\\Temp, pnputil, powercfg и дефрагментация "
                    "могут не сработать. Перезапустите от имени администратора.")
        print("ВНИМАНИЕ: для полной функциональности запустите программу от имени администратора.",
              file=sys.stderr)

    state_path = Path(log_dir) / STATE_FILE

    # Показать последний отчёт и выйти (без выполнения задач).
    if args.report:
        return print_last_report(config.report_dir)

    # Поверхностная чистка: только очистка мусора.
    if args.light or args.mode == "light":
        report = run_light_optimization(config)
        log.info("Поверхностная чистка завершена.")
        safe_print(format_report(report))
        return 0

    # Полный однократный прогон.
    if args.once or args.mode == "full":
        report = run_optimization(config, state_path)
        log.info("Однократный запуск завершён.")
        safe_print(format_report(report))
        return 0

    # Догоняющий запуск пропущенных задач (только в режиме планировщика).
    if config.catch_up_on_wake:
        try:
            mode = _missed_run_mode(config, load_state(state_path))
            if mode == "light":
                log.info("Пропущена поверхностная чистка — выполняю догоняющий прогон (light).")
                run_light_optimization(config)
            elif mode == "full":
                log.info("Пропущен полный цикл — выполняю догоняющий прогон (full).")
                run_optimization(config, state_path)
        except Exception as exc:
            log.exception("Ошибка догоняющего запуска: %s", exc)

    # Режим планировщика: разные функции для поверхностной и глубокой чистки.
    scheduler = TaskScheduler([], timezone=config.timezone)
    if config.light_times:
        scheduler.add_daily(config.light_times, lambda: run_light_optimization(config))
    full_times = config.effective_full_times()
    if full_times:
        scheduler.add_daily(full_times, lambda: run_optimization(config, state_path))

    # Опционально: периодический tick агента питания в основном цикле —
    # на случай, если агент не запущен отдельным процессом (power_agent_main).
    # При power_agent_enabled=false ничего не меняется.
    if getattr(config, "power_agent_enabled", False):
        from .advanced.power_agent import PowerAgent

        agent = PowerAgent(config)
        scheduler.add_periodic(
            float(config.power_agent_interval_seconds),
            agent.tick,
        )
        log.info("Агент питания встроен в основной цикл (каждые %d с).",
                 config.power_agent_interval_seconds)

    try:
        scheduler.run_forever()
    except KeyboardInterrupt:
        log.info("Получен сигнал завершения. Останавливаю планировщик.")
        scheduler.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

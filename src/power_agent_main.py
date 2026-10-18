"""Точка входа фонового агента питания.

Запуск (от имени администратора, иначе powercfg не сработает):
    python -m src.power_agent_main --config config/settings.yaml

Агент работает до сигнала остановки (Ctrl+C, SIGTERM/SIGBREAK) или
завершается сразу, если power_agent.enabled=false в конфиге.
"""
from __future__ import annotations

import argparse
import signal
import sys
from typing import List, Optional

from .advanced.power_agent import PowerAgent
from .core.config import Config
from .core.constants import DEFAULT_CONFIG_PATH
from .core.logger import get_logger, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PC Optimizer Pro — фоновый агент питания")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                        help="путь к конфигурационному YAML-файлу")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    config = Config.from_yaml(args.config)
    setup_logging(log_dir=config.log_dir, console=False, level=config.log_level)
    log = get_logger("power_agent_main")

    log.info("Агент питания: запуск CLI (enabled=%s, конфиг %s).",
             config.power_agent_enabled, args.config)

    agent = PowerAgent(config)

    def _handle_signal(signum, _frame) -> None:
        log.info("Получен сигнал %s — останавливаю агент.", signum)
        agent.stop()

    for signame in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, signame):
            try:
                signal.signal(getattr(signal, signame), _handle_signal)
            except (ValueError, OSError):  # не в главном потоке
                pass

    try:
        agent.run_forever()
    except KeyboardInterrupt:
        log.info("Получен Ctrl+C — останавливаю агент.")
        agent.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

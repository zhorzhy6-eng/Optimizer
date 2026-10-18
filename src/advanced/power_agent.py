"""Фоновый агент питания: постоянно классифицирует контекст пользователя
(игра / тяжёлая задача / офис / простой) и переключает схему электропитания
через существующий PowerManager.

Безопасность и правила:
- агент НЕ закрывает процессы — только переключает схему питания;
- powercfg не вызывается, если контекст не изменился;
- гистерезис: после выхода из игры схема не меняется в течение
  `game_cooldown_seconds` (защита от «дрожания» при перезапуске игры);
- защита от частых переключений: больше 3 за 60 секунд — пропуск с warning;
- состояние (контекст, схема, история) пишется в logs/power_context.json
  атомарно через src/core/power_context.py.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional

from ..core import power_context
from ..core.logger import get_logger
from ..core.system.windows import idle_seconds

if TYPE_CHECKING:  # только для аннотаций, не импортируется в рантайме
    from ..optimization.process_monitor import ProcessInfo

log = get_logger("power_agent")

ACTIVE_IDLE_LIMIT_SECONDS = 120.0  # пользователь «активен», если idle меньше
HEAVY_CPU_THRESHOLD = 50.0          # порог CPU для «тяжёлой» задачи, %
MAX_SWITCHES_PER_MINUTE = 3


class PowerAgent:
    """Фоновый переключатель схем питания по контексту пользователя."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log
        self._stop_event = threading.Event()
        self._idle_func = idle_seconds
        self._state: dict = power_context.load(getattr(config, "log_dir", "logs"))
        self._last_description = ""

    # ------------------------------------------------------------------ #
    # Управление жизненным циклом
    # ------------------------------------------------------------------ #
    def run_forever(self, poll_interval: Optional[float] = None) -> None:
        """Основной цикл: tick каждые poll_interval секунд (по умолчанию из конфига).

        Если агент выключен в конфиге — завершается сразу, ничего не делая.
        """
        if not getattr(self.config, "power_agent_enabled", False):
            self.log.debug("Агент питания выключен (power_agent.enabled=false).")
            return

        interval = (poll_interval if poll_interval is not None
                    else float(self.config.power_agent_interval_seconds))
        self.log.info("Агент питания запущен (интервал %.0f с, конфиг config/settings.yaml).",
                      interval)

        try:
            while not self._stop_event.is_set():
                self.tick()
                self._stop_event.wait(interval)
        finally:
            self.log.info("Агент питания остановлен")
            self._save_context()

    def stop(self) -> None:
        """Останавливает цикл run_forever (безопасен при вызове из любого потока)."""
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    # Один шаг наблюдения
    # ------------------------------------------------------------------ #
    def tick(self) -> str:
        """Один шаг: собрать процессы, классифицировать, применить схему.

        Возвращает определённый контекст (или "error" при исключении).
        Исключения не прерывают работу агента.
        """
        now = time.time()
        try:
            from ..optimization.process_monitor import ProcessMonitor

            procs = ProcessMonitor(self.config, logger=self.log).list_processes(
                warmup=False, warmup_delay=0)
            idle = self._idle_func()
            context = self._classify(procs, idle)
            self._last_description = self._describe(procs, context, idle)

            self._log_debug_stats(procs, context)

            current = str(self._state.get("current", ""))
            if context == current:
                self.log.debug("Контекст не изменился (%s), схема не переключается",
                               context or "нет")
                return context

            if not self._should_switch(context, now):
                self.log.debug("Гистерезис: с момента last_change прошло %.0f с, порог %d с — ждём",
                               now - float(self._state.get("last_switch") or 0),
                               int(self.config.power_agent_game_cooldown_seconds))
                return context

            switches = int(self._state.get("switches_last_minute", 0))
            if switches > MAX_SWITCHES_PER_MINUTE:
                self.log.warning("Слишком частые переключения (%d за 60 с) — пропускаю", switches)
                return context

            self._apply(context)
            return context
        except Exception as exc:
            self.log.exception("Ошибка tick() агента питания: %s", exc)
            return "error"

    # ------------------------------------------------------------------ #
    # Классификация контекста (слой 1: правила)
    # ------------------------------------------------------------------ #
    def _classify(self, procs: List["ProcessInfo"], idle_seconds_value: Optional[float] = None) -> str:
        """Определяет контекст по списку процессов и времени простоя.

        Приоритет правил:
        1. game  — процесс из game_processes, пользователь активен (idle < 120 с);
        2. heavy — процесс из heavy_task_processes с CPU >= 50 %;
        3. office — процесс из office_processes, пользователь активен;
        4. idle  — idle >= idle_minutes * 60;
        5. fallback — прежний контекст (схема не трогается).

        Лаунчеры из launchers_to_ignore сами по себе игру НЕ включают
        (игра определяется только процессом из game_processes).
        """
        if idle_seconds_value is None:
            idle_seconds_value = self._idle_func()

        games = {g.strip().lower() for g in self.config.game_processes}
        office = {o.strip().lower() for o in self.config.office_processes}
        heavy_names = {h.strip().lower() for h in self.config.heavy_task_processes}
        _launchers = {l.strip().lower() for l in self.config.launchers_to_ignore}

        active = idle_seconds_value < ACTIVE_IDLE_LIMIT_SECONDS
        heavy_cpu = 0.0
        names = set()

        for proc in procs:
            if proc.pid == 0:  # System Idle Process — не учитываем
                continue
            name = (proc.name or "").strip().lower()
            names.add(name)
            if name in heavy_names:
                heavy_cpu = max(heavy_cpu, float(proc.cpu_percent or 0.0))

        # 1. Игра (только реальные игровые процессы, лаунчеры не считаются)
        if active and names & games:
            return "game"

        # 2. Тяжёлая задача (рендеринг/компиляция и т.п.)
        if heavy_cpu >= HEAVY_CPU_THRESHOLD:
            return "heavy"

        # 3. Офис
        if active and names & office:
            return "office"

        # 4. Простой
        if idle_seconds_value >= self.config.idle_minutes * 60:
            return "idle"

        # 5. Fallback: сохранить текущий контекст (может быть пустым при первом запуске)
        return str(self._state.get("current", ""))

    # ------------------------------------------------------------------ #
    # Гистерезис
    # ------------------------------------------------------------------ #
    def _should_switch(self, context: str, now: float) -> bool:
        """Разрешает переключение с учётом гистерезиса.

        Правила:
        - переход В game — сразу;
        - переход ИЗ game — только после game_cooldown_seconds с момента
          входа в игру (last_switch);
        - остальные переходы (idle/office/heavy) — сразу;
        - контекст не изменился — False (вызывается только при изменении,
          но проверка оставлена для полноты).
        """
        current = str(self._state.get("current", ""))
        if context == current:
            return False

        if current == "game" and context != "game":
            last_switch = float(self._state.get("last_switch") or 0.0)
            elapsed = now - last_switch
            if elapsed < float(self.config.power_agent_game_cooldown_seconds):
                return False
        return True

    # ------------------------------------------------------------------ #
    # Применение схемы
    # ------------------------------------------------------------------ #
    def _apply(self, context: str) -> None:
        """Переключает схему питания для контекста и сохраняет состояние."""
        scheme = self.config.power_agent_context_map.get(context)
        if not scheme:
            self.log.warning("Для контекста %s не задана схема в context_map", context)
            return

        from ..optimization.power_manager import PowerManager

        manager = PowerManager(self.config, logger=self.log)
        if not manager.set_scheme(scheme):
            self.log.warning("Не удалось применить схему %s — PowerManager вернул failed", scheme)
            return

        now = time.time()
        self._state = power_context.update(self._state, context, scheme, now)
        self._save_context()
        self.log.info("Контекст: %s (%s) → %s", context, self._last_description, scheme)

    # ------------------------------------------------------------------ #
    # Состояние и описание
    # ------------------------------------------------------------------ #
    def _load_context(self) -> dict:
        self._state = power_context.load(getattr(self.config, "log_dir", "logs"))
        return self._state

    def _save_context(self) -> None:
        power_context.save(self._state, getattr(self.config, "log_dir", "logs"))

    def _describe(self, procs: List["ProcessInfo"], context: str, idle_seconds_value: float) -> str:
        """Короткое человекочитаемое описание контекста для лога."""
        found: Dict[str, object] = {}
        for proc in procs:
            if proc.pid != 0:
                found[(proc.name or "").lower()] = proc

        for wanted in (self.config.game_processes if context == "game" else
                       self.config.heavy_task_processes if context == "heavy" else
                       self.config.office_processes if context == "office" else []):
            proc = found.get(str(wanted).strip().lower())
            if proc is not None:
                return f"{proc.name}, CPU {proc.cpu_percent:.0f}%"

        minutes = idle_seconds_value / 60.0
        top = sorted((p for p in procs if p.pid != 0 and p.cpu_percent > 0),
                     key=lambda p: p.cpu_percent, reverse=True)[:1]
        cpu = f", CPU {top[0].cpu_percent:.0f}%" if top else ""
        return f"idle {minutes:.0f} мин{cpu}"

    def _log_debug_stats(self, procs: List["ProcessInfo"], context: str) -> None:
        games = {g.strip().lower() for g in self.config.game_processes}
        office = {o.strip().lower() for o in self.config.office_processes}
        game_count = sum(1 for p in procs if p.pid != 0 and (p.name or "").lower() in games)
        office_count = sum(1 for p in procs if p.pid != 0 and (p.name or "").lower() in office)
        self.log.debug("Процессов собрано: %d, игровых: %d, офисных: %d, контекст: %s",
                       len(procs), game_count, office_count, context)

"""Загрузка конфигурации из YAML-файла.

Файл по умолчанию: config/settings.yaml.
Если файл отсутствует или повреждён — используются значения по умолчанию,
программа при этом не падает (ошибка логируется).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .logger import get_logger

try:
    import yaml
except ImportError:  # pragma: no cover - на случай отсутствия PyYAML
    yaml = None  # type: ignore[assignment]

log = get_logger("config")


def _to_float(value, default: float) -> float:
    """Безопасно приводит значение к float, иначе возвращает default.

    Нужна, чтобы одна опечатка в settings.yaml не отбрасывала всю
    конфигурацию целиком (раньше исключение откатывало все настройки).
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        log.warning("Некорректное числовое значение %r — использую %s.", value, default)
        return default


def _to_int(value, default: int) -> int:
    """Безопасно приводит значение к int, иначе возвращает default."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        log.warning("Некорректное целое значение %r — использую %s.", value, default)
        return default


DEFAULT_POWER_SCHEMES: Dict[str, str] = {
    "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "power_saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
    # Ultimate Performance доступна не на всех ПК; при недоступности
    # powercfg вернёт ошибку, а программа откатится на high_performance.
    "ultimate": "e9a42b02-d5df-448d-aa00-03f14749eb61",
}


@dataclass
class Config:
    """Настройки программы, собранные из settings.yaml."""

    # Планировщик
    schedule_times: List[str] = field(default_factory=lambda: ["12:00", "18:00"])
    # Времена для поверхностной (light) и глубокой (full) оптимизации.
    # Если оба списка пусты, используется старый формат: schedule_times -> full.
    light_times: List[str] = field(default_factory=list)
    full_times: List[str] = field(default_factory=list)
    timezone: Optional[str] = None
    catch_up_on_wake: bool = True

    # Очистка
    temp_paths: List[str] = field(default_factory=lambda: [r"%TEMP%", r"C:\Windows\Temp"])
    clean_recycle_bin: bool = True
    log_retention_days: int = 7

    # Мониторинг процессов
    cpu_threshold_percent: float = 50.0
    ram_threshold_percent: float = 50.0
    idle_minutes: int = 10
    unwanted_processes: List[str] = field(default_factory=list)

    # Энергопотребление
    game_processes: List[str] = field(default_factory=list)
    office_processes: List[str] = field(default_factory=list)
    # Схема питания для каждого сценария (имя из power_schemes).
    game_scheme: str = "high_performance"
    office_scheme: str = "balanced"
    idle_scheme: str = "power_saver"
    power_schemes: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_POWER_SCHEMES))

    # Дополнительные списки процессов для классификации контекста агентом питания
    launchers_to_ignore: List[str] = field(default_factory=list)
    heavy_task_processes: List[str] = field(default_factory=list)

    # Агент питания (фоновое переключение схем; по умолчанию выключен)
    power_agent_enabled: bool = False
    power_agent_interval_seconds: int = 10
    power_agent_game_cooldown_seconds: int = 180
    power_agent_context_map: Dict[str, str] = field(default_factory=lambda: {
        "game": "high_performance",
        "heavy": "high_performance",
        "office": "balanced",
        "idle": "power_saver",
    })

    # Дефрагментация
    defrag_drives: List[str] = field(default_factory=lambda: ["C:"])

    # Автозагрузка (анализ всегда безопасен, отключение — по списку)
    startup_enabled: bool = True
    startup_disable_entries: List[str] = field(default_factory=list)

    # Службы (по умолчанию только анализ)
    services_enabled: bool = False
    services_disable: List[str] = field(default_factory=list)
    services_protected: List[str] = field(default_factory=list)

    # Сеть (по умолчанию только сброс DNS-кэша)
    network_enabled: bool = False
    network_flush_dns: bool = True
    network_set_dns: bool = False
    network_dns_servers: List[str] = field(default_factory=list)
    network_tune_tcp: bool = False

    # Здоровье дисков (только чтение SMART)
    disk_health_enabled: bool = True
    disk_health_warn_free_percent: float = 10.0

    # Дубликаты и большие файлы (удаление выключено по умолчанию)
    duplicates_enabled: bool = False
    duplicates_scan_paths: List[str] = field(default_factory=list)
    duplicates_min_size_mb: float = 10.0
    duplicates_find: bool = True
    duplicates_delete: bool = False
    duplicates_max_files: int = 20000

    # Обновления winget (по умолчанию только список доступных)
    winget_enabled: bool = False
    winget_upgrade_all: bool = False

    # Температура и троттлинг
    thermal_enabled: bool = True
    thermal_max_temperature_c: float = 85.0
    thermal_min_clock_percent: float = 60.0
    thermal_switch_to_power_saver: bool = False

    # Драйверы
    driver_folder: str = r"C:\Drivers"
    enable_driver_update: bool = False
    driver_update_tool: str = "winget"  # "winget" | "uso"

    # Логирование / отчёты
    log_level: str = "TRACE"
    log_dir: str = "logs"
    generate_report: bool = False
    report_dir: str = "logs"

    def all_times(self) -> List[str]:
        """Все времена запуска (light + full) — для догоняющего запуска."""
        combined = list(dict.fromkeys(self.light_times + self.full_times))
        return combined or self.schedule_times

    def effective_full_times(self) -> List[str]:
        """Времена полного цикла с учётом обратной совместимости.

        Если `full_times` не задан и `light_times` тоже пуст, используется
        старый ключ `times` (все запуски = полный цикл).
        """
        if self.full_times:
            return list(self.full_times)
        if self.light_times:
            return []
        return list(self.schedule_times)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        """Загружает конфигурацию из YAML-файла.

        При любой ошибке возвращает экземпляр со значениями по умолчанию.
        """
        cfg = cls()
        path = Path(path)
        try:
            if yaml is None:
                log.warning("PyYAML не установлен — используются значения по умолчанию.")
                return cfg

            if not path.exists():
                log.warning("Файл конфигурации не найден: %s. Используются значения по умолчанию.", path)
                return cfg

            # utf-8-sig устойчив к BOM (его может добавить PowerShell при правке файла).
            with path.open("r", encoding="utf-8-sig") as fh:
                raw = yaml.safe_load(fh) or {}

            if not isinstance(raw, dict):
                raise ValueError("корень YAML должен быть словарём (mapping)")

            # --- Планировщик ---
            sched = raw.get("schedule") or {}
            if isinstance(sched, dict):
                times = sched.get("times")
                if isinstance(times, list) and times:
                    cfg.schedule_times = [str(t) for t in times]
                light = sched.get("light_times")
                full = sched.get("full_times")
                has_light = isinstance(light, list)
                has_full = isinstance(full, list)
                if has_light:
                    cfg.light_times = [str(t) for t in light]
                if has_full:
                    cfg.full_times = [str(t) for t in full]
                if not has_light and not has_full:
                    # Обратная совместимость: старый формат times -> полный цикл.
                    cfg.full_times = list(cfg.schedule_times)
                if sched.get("timezone") is not None:
                    cfg.timezone = str(sched["timezone"])
                if isinstance(sched.get("catch_up_on_wake"), bool):
                    cfg.catch_up_on_wake = sched["catch_up_on_wake"]

            # --- Очистка ---
            cleaner = raw.get("cleaner") or {}
            if isinstance(cleaner, dict):
                if isinstance(cleaner.get("temp_paths"), list):
                    cfg.temp_paths = [str(p) for p in cleaner["temp_paths"]]
                if isinstance(cleaner.get("clean_recycle_bin"), bool):
                    cfg.clean_recycle_bin = cleaner["clean_recycle_bin"]
                if isinstance(cleaner.get("log_retention_days"), int):
                    cfg.log_retention_days = cleaner["log_retention_days"]
                elif cleaner.get("log_retention_days") is not None:
                    cfg.log_retention_days = _to_int(cleaner["log_retention_days"], cfg.log_retention_days)

            # --- Мониторинг процессов ---
            pm = raw.get("process_monitor") or {}
            if isinstance(pm, dict):
                cfg.cpu_threshold_percent = _to_float(
                    pm.get("cpu_threshold_percent"), cfg.cpu_threshold_percent)
                cfg.ram_threshold_percent = _to_float(
                    pm.get("ram_threshold_percent"), cfg.ram_threshold_percent)
                cfg.idle_minutes = _to_int(pm.get("idle_minutes"), cfg.idle_minutes)
                if isinstance(pm.get("unwanted_processes"), list):
                    cfg.unwanted_processes = [str(p) for p in pm["unwanted_processes"]]

            # --- Энергопотребление ---
            power = raw.get("power") or {}
            if isinstance(power, dict):
                if isinstance(power.get("game_processes"), list):
                    cfg.game_processes = [str(p) for p in power["game_processes"]]
                if isinstance(power.get("office_processes"), list):
                    cfg.office_processes = [str(p) for p in power["office_processes"]]
                if isinstance(power.get("launchers_to_ignore"), list):
                    cfg.launchers_to_ignore = [str(p) for p in power["launchers_to_ignore"]]
                if isinstance(power.get("heavy_task_processes"), list):
                    cfg.heavy_task_processes = [str(p) for p in power["heavy_task_processes"]]
                if power.get("game_scheme") is not None:
                    cfg.game_scheme = str(power["game_scheme"])
                if power.get("office_scheme") is not None:
                    cfg.office_scheme = str(power["office_scheme"])
                if power.get("idle_scheme") is not None:
                    cfg.idle_scheme = str(power["idle_scheme"])
                if isinstance(power.get("schemes"), dict):
                    merged = dict(DEFAULT_POWER_SCHEMES)
                    merged.update({str(k): str(v) for k, v in power["schemes"].items()})
                    cfg.power_schemes = merged

            # --- Агент питания ---
            agent = raw.get("power_agent") or {}
            if isinstance(agent, dict):
                if isinstance(agent.get("enabled"), bool):
                    cfg.power_agent_enabled = agent["enabled"]
                cfg.power_agent_interval_seconds = max(1, _to_int(
                    agent.get("interval_seconds"), cfg.power_agent_interval_seconds))
                cfg.power_agent_game_cooldown_seconds = max(0, _to_int(
                    agent.get("game_cooldown_seconds"), cfg.power_agent_game_cooldown_seconds))
                if isinstance(agent.get("context_map"), dict):
                    merged_map = dict(cfg.power_agent_context_map)
                    merged_map.update({str(k): str(v) for k, v in agent["context_map"].items()})
                    cfg.power_agent_context_map = merged_map

            # --- Дефрагментация ---
            df = raw.get("defrag") or {}
            if isinstance(df, dict) and isinstance(df.get("drives"), list):
                cfg.defrag_drives = [str(d) for d in df["drives"]]

            # --- Автозагрузка ---
            startup = raw.get("startup") or {}
            if isinstance(startup, dict):
                if isinstance(startup.get("enabled"), bool):
                    cfg.startup_enabled = startup["enabled"]
                if isinstance(startup.get("disable_entries"), list):
                    cfg.startup_disable_entries = [str(x) for x in startup["disable_entries"]]

            # --- Службы ---
            services = raw.get("services") or {}
            if isinstance(services, dict):
                if isinstance(services.get("enabled"), bool):
                    cfg.services_enabled = services["enabled"]
                if isinstance(services.get("disable_services"), list):
                    cfg.services_disable = [str(x) for x in services["disable_services"]]
                if isinstance(services.get("protected_services"), list):
                    cfg.services_protected = [str(x) for x in services["protected_services"]]

            # --- Сеть ---
            network = raw.get("network") or {}
            if isinstance(network, dict):
                if isinstance(network.get("enabled"), bool):
                    cfg.network_enabled = network["enabled"]
                if isinstance(network.get("flush_dns"), bool):
                    cfg.network_flush_dns = network["flush_dns"]
                if isinstance(network.get("set_dns"), bool):
                    cfg.network_set_dns = network["set_dns"]
                if isinstance(network.get("dns_servers"), list):
                    cfg.network_dns_servers = [str(x) for x in network["dns_servers"]]
                if isinstance(network.get("tune_tcp"), bool):
                    cfg.network_tune_tcp = network["tune_tcp"]

            # --- Здоровье дисков ---
            health = raw.get("disk_health") or {}
            if isinstance(health, dict):
                if isinstance(health.get("enabled"), bool):
                    cfg.disk_health_enabled = health["enabled"]
                cfg.disk_health_warn_free_percent = _to_float(
                    health.get("warn_free_percent"), cfg.disk_health_warn_free_percent)

            # --- Дубликаты ---
            dup = raw.get("duplicates") or {}
            if isinstance(dup, dict):
                if isinstance(dup.get("enabled"), bool):
                    cfg.duplicates_enabled = dup["enabled"]
                if isinstance(dup.get("scan_paths"), list):
                    cfg.duplicates_scan_paths = [str(x) for x in dup["scan_paths"]]
                cfg.duplicates_min_size_mb = _to_float(
                    dup.get("min_size_mb"), cfg.duplicates_min_size_mb)
                if isinstance(dup.get("find_duplicates"), bool):
                    cfg.duplicates_find = dup["find_duplicates"]
                if isinstance(dup.get("delete_duplicates"), bool):
                    cfg.duplicates_delete = dup["delete_duplicates"]
                cfg.duplicates_max_files = _to_int(
                    dup.get("max_files"), cfg.duplicates_max_files)

            # --- winget ---
            winget = raw.get("winget") or {}
            if isinstance(winget, dict):
                if isinstance(winget.get("enabled"), bool):
                    cfg.winget_enabled = winget["enabled"]
                if isinstance(winget.get("upgrade_all"), bool):
                    cfg.winget_upgrade_all = winget["upgrade_all"]

            # --- Температура ---
            thermal = raw.get("thermal") or {}
            if isinstance(thermal, dict):
                if isinstance(thermal.get("enabled"), bool):
                    cfg.thermal_enabled = thermal["enabled"]
                cfg.thermal_max_temperature_c = _to_float(
                    thermal.get("max_temperature_c"), cfg.thermal_max_temperature_c)
                cfg.thermal_min_clock_percent = _to_float(
                    thermal.get("min_clock_percent"), cfg.thermal_min_clock_percent)
                if isinstance(thermal.get("switch_to_power_saver"), bool):
                    cfg.thermal_switch_to_power_saver = thermal["switch_to_power_saver"]

            # --- Драйверы ---
            drv = raw.get("drivers") or {}
            if isinstance(drv, dict):
                if drv.get("driver_folder") is not None:
                    cfg.driver_folder = str(drv["driver_folder"])
                if isinstance(drv.get("enable_driver_update"), bool):
                    cfg.enable_driver_update = drv["enable_driver_update"]
                if drv.get("update_tool") in ("winget", "uso"):
                    cfg.driver_update_tool = str(drv["update_tool"])

            # --- Логирование ---
            lg = raw.get("logging") or {}
            if isinstance(lg, dict):
                if lg.get("level") is not None:
                    cfg.log_level = str(lg["level"])
                if lg.get("dir") is not None:
                    cfg.log_dir = str(lg["dir"])
                if isinstance(lg.get("generate_report"), bool):
                    cfg.generate_report = lg["generate_report"]

            log.info("Конфигурация загружена из %s", path)
        except Exception as exc:
            log.exception("Ошибка загрузки конфигурации %s: %s. Используются значения по умолчанию.", path, exc)
        return cfg

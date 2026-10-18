"""Сетевые настройки: сброс DNS-кэша, DNS-серверы, TCP-тюнинг.

Безопасность:
- по умолчанию выполняется только безопасный сброс DNS-кэша;
- смена DNS и TCP-параметров возможна лишь при явном включении в конфиге;
- перед изменением текущие значения сохраняются в
  `logs/network_backup.json`, поэтому `restore_dns()` возвращает всё как было.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from ..core.system import shell
from ..core.logger import get_logger

log = get_logger("network_tuner")

_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


class NetworkTuner:
    """Управляет сетевыми настройками с сохранением прежних значений."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log
        self.backup_path = Path(getattr(config, "log_dir", "logs")) / "network_backup.json"

    # ------------------------------------------------------------------ #
    # DNS-кэш
    # ------------------------------------------------------------------ #
    def flush_dns(self) -> bool:
        """Сбрасывает DNS-кэш (ipconfig /flushdns)."""
        try:
            result = shell.run(["ipconfig", "/flushdns"], timeout=60)
            ok = result.returncode == 0
            self.log.info("Сброс DNS-кэша: %s.", "успешно" if ok else f"код {result.returncode}")
            return ok
        except Exception as exc:
            self.log.warning("Ошибка сброса DNS-кэша: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # DNS-серверы
    # ------------------------------------------------------------------ #
    def get_dns(self) -> List[Dict[str, str]]:
        """Текущие DNS-серверы по интерфейсам."""
        command = (
            "Get-DnsClientServerAddress -AddressFamily IPv4 | "
            "Where-Object { $_.ServerAddresses } | "
            "Select-Object InterfaceAlias,ServerAddresses | ConvertTo-Json -Compress"
        )
        try:
            result = shell.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command], timeout=120)
            data = json.loads((result.stdout or "").strip() or "[]")
        except Exception as exc:
            self.log.debug("Не удалось получить DNS-серверы: %s", exc)
            return []
        if isinstance(data, dict):
            data = [data]
        servers: List[Dict[str, str]] = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            addresses = item.get("ServerAddresses") or []
            if isinstance(addresses, str):
                addresses = [addresses]
            servers.append({
                "interface": str(item.get("InterfaceAlias", "")),
                "servers": ", ".join(str(a) for a in addresses),
            })
        return servers

    def _load_backup(self) -> dict:
        try:
            if self.backup_path.exists():
                return json.loads(self.backup_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            self.log.debug("Не удалось прочитать %s: %s", self.backup_path, exc)
        return {}

    def _save_backup(self, data: dict) -> None:
        try:
            self.backup_path.parent.mkdir(parents=True, exist_ok=True)
            self.backup_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.log.warning("Не удалось сохранить %s: %s", self.backup_path, exc)

    def set_dns(self, servers: List[str]) -> List[str]:
        """Устанавливает DNS-серверы на активных интерфейсах, сохраняя прежние."""
        valid = [s for s in servers if _IPV4_RE.match(str(s).strip())]
        if not valid:
            self.log.warning("Не заданы корректные IPv4 DNS-серверы — изменение пропущено.")
            return []

        backup = self._load_backup()
        changed: List[str] = []
        for entry in self.get_dns():
            interface = entry["interface"]
            if not interface or interface.lower().startswith("loopback"):
                continue
            backup.setdefault("dns", {}).setdefault(interface, entry["servers"])
            try:
                result = shell.run([
                    "powershell", "-NoProfile", "-NonInteractive", "-Command",
                    f"Set-DnsClientServerAddress -InterfaceAlias '{interface}' "
                    f"-ServerAddresses {','.join(valid)}",
                ], timeout=120)
                if result.returncode == 0:
                    changed.append(interface)
                    self.log.info("DNS для «%s» изменён на %s.", interface, ", ".join(valid))
                else:
                    self.log.warning("Не удалось изменить DNS для «%s»: %s",
                                     interface, (result.stderr or "").strip())
            except Exception as exc:
                self.log.warning("Ошибка смены DNS для «%s»: %s", interface, exc)

        self._save_backup(backup)
        return changed

    def restore_dns(self) -> List[str]:
        """Возвращает DNS-серверы из резервного файла (или сбрасывает в DHCP)."""
        backup = self._load_backup()
        dns_backup = backup.get("dns", {})
        restored: List[str] = []
        for interface, servers in list(dns_backup.items()):
            try:
                command = (f"Set-DnsClientServerAddress -InterfaceAlias '{interface}' "
                           f"-ServerAddresses {servers}") if servers else \
                          f"Set-DnsClientServerAddress -InterfaceAlias '{interface}' -ResetServerAddresses"
                result = shell.run([
                    "powershell", "-NoProfile", "-NonInteractive", "-Command", command], timeout=120)
                if result.returncode == 0:
                    restored.append(interface)
                    dns_backup.pop(interface, None)
            except Exception as exc:
                self.log.warning("Не удалось вернуть DNS для «%s»: %s", interface, exc)
        self._save_backup(backup)
        return restored

    # ------------------------------------------------------------------ #
    # TCP-тюнинг
    # ------------------------------------------------------------------ #
    def tcp_global(self) -> Dict[str, str]:
        """Текущие глобальные параметры TCP (netsh int tcp show global)."""
        result: Dict[str, str] = {}
        try:
            output = shell.run(["netsh", "int", "tcp", "show", "global"], timeout=60).stdout or ""
            for line in output.splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    if key.strip():
                        result[key.strip()] = value.strip()
        except Exception as exc:
            self.log.debug("Не удалось прочитать параметры TCP: %s", exc)
        return result

    def tune_tcp(self) -> bool:
        """Включает стандартный профиль TCP (autotuning normal, RSS включён)."""
        try:
            current = self.tcp_global()
            if current:
                backup = self._load_backup()
                backup.setdefault("tcp", current)
                self._save_backup(backup)

            result = shell.run([
                "netsh", "int", "tcp", "set", "global",
                "autotuninglevel=normal", "rss=enabled",
            ], timeout=60)
            ok = result.returncode == 0
            self.log.info("TCP-тюнинг: %s.", "применён" if ok else f"код {result.returncode}")
            return ok
        except Exception as exc:
            self.log.warning("Ошибка TCP-тюнинга: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        """Сетевые операции согласно конфигурации."""
        report: dict = {"dns_flushed": False, "dns_changed": [], "tcp_tuned": False, "errors": []}
        try:
            if not getattr(self.config, "network_enabled", False):
                self.log.info("Сетевой модуль выключен в конфигурации — пропуск.")
                return report

            if getattr(self.config, "network_flush_dns", True):
                report["dns_flushed"] = self.flush_dns()

            if getattr(self.config, "network_set_dns", False):
                servers = list(getattr(self.config, "network_dns_servers", []) or [])
                report["dns_changed"] = self.set_dns(servers)

            if getattr(self.config, "network_tune_tcp", False):
                report["tcp_tuned"] = self.tune_tcp()
        except Exception as exc:
            self.log.exception("Неожиданная ошибка NetworkTuner.run: %s", exc)
            report["errors"].append(str(exc))
        return report

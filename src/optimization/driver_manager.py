"""Управление драйверами через PnPUtil (встроен в Windows, требует админа).

Поддерживаемые операции:
- установка из заранее подготовленной папки: pnputil /add-driver "*.inf" /install
- удаление: pnputil /delete-driver oem0.inf /force
- просмотр: pnputil /enum-drivers
- обновление: winget upgrade --all или UsoClient ScanInstallWait

Загрузка драйверов с сайтов производителей не автоматизируется (нет API) —
устанавливаются только драйверы из подготовленной папки либо через winget.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

from ..core.system import shell
from ..core.logger import get_logger

log = get_logger("driver_manager")


class DriverManager:
    """Обёртка над pnputil / winget / UsoClient."""

    def __init__(self, config, logger=None) -> None:
        self.config = config
        self.log = logger or log

    def _run(self, args: List[str], timeout: int = 3600) -> subprocess.CompletedProcess:
        return shell.run(args, timeout=timeout)

    # ------------------------------------------------------------------ #
    def enum_drivers(self) -> str:
        """Выводит список установленных драйверов (pnputil /enum-drivers)."""
        try:
            result = self._run(["pnputil", "/enum-drivers"])
            output = (result.stdout or "") + (result.stderr or "")
            self.log.info("Список драйверов получен (код %s).", result.returncode)
            return output
        except Exception as exc:
            self.log.warning("Ошибка pnputil /enum-drivers: %s", exc)
            return ""

    def install_from_folder(self, folder: str | None = None) -> List[str]:
        """Устанавливает все *.inf из папки через pnputil /add-driver ... /install.

        Returns:
            список путей к успешно установленным .inf файлам.
        """
        installed: List[str] = []
        try:
            root = Path(folder if folder is not None else self.config.driver_folder)
            if not root.is_dir():
                self.log.warning("Папка драйверов не найдена: %s", root)
                return installed

            inf_files = sorted(root.rglob("*.inf"))
            if not inf_files:
                self.log.info("В папке %s нет .inf файлов.", root)
                return installed

            for inf in inf_files:
                try:
                    result = self._run(["pnputil", "/add-driver", str(inf), "/install"])
                    if result.returncode == 0:
                        installed.append(str(inf))
                        self.log.info("Драйвер установлен: %s", inf)
                    else:
                        self.log.warning("Не удалось установить %s (код %s): %s",
                                         inf, result.returncode, result.stderr.strip())
                except Exception as exc:
                    self.log.warning("Ошибка установки %s: %s", inf, exc)
        except Exception as exc:
            self.log.exception("Неожиданная ошибка install_from_folder: %s", exc)
        return installed

    def delete_driver(self, oem_name: str, force: bool = True) -> bool:
        """Удаляет драйвер: pnputil /delete-driver <oem_name> [/force]."""
        try:
            args = ["pnputil", "/delete-driver", oem_name]
            if force:
                args.append("/force")
            result = self._run(args)
            if result.returncode == 0:
                self.log.info("Драйвер удалён: %s", oem_name)
                return True
            self.log.warning("Не удалось удалить драйвер %s (код %s): %s",
                             oem_name, result.returncode, result.stderr.strip())
            return False
        except Exception as exc:
            self.log.warning("Ошибка удаления драйвера %s: %s", oem_name, exc)
            return False

    # ------------------------------------------------------------------ #
    def update_via_winget(self) -> bool:
        """Обновляет пакеты (в т.ч. драйверы) через winget upgrade --all."""
        try:
            result = self._run([
                "winget", "upgrade", "--all",
                "--accept-source-agreements", "--accept-package-agreements",
            ])
            ok = result.returncode == 0
            self.log.info("winget upgrade --all завершён: %s.", "успешно" if ok else f"код {result.returncode}")
            return ok
        except Exception as exc:
            self.log.warning("Ошибка winget upgrade: %s", exc)
            return False

    def update_via_uso(self) -> bool:
        """Запускает проверку/установку обновлений Windows (UsoClient ScanInstallWait)."""
        try:
            result = self._run(["UsoClient", "ScanInstallWait"])
            ok = result.returncode == 0
            self.log.info("UsoClient ScanInstallWait завершён: %s.", "успешно" if ok else f"код {result.returncode}")
            return ok
        except Exception as exc:
            self.log.warning("Ошибка UsoClient: %s", exc)
            return False

    def update_all(self) -> bool:
        """Автообновление в зависимости от настройки driver_update_tool."""
        tool = self.config.driver_update_tool
        if tool == "uso":
            return self.update_via_uso()
        return self.update_via_winget()

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        """Полный цикл управления драйверами; возвращает отчёт."""
        report = {"installed": [], "updated": False}
        try:
            report["installed"] = self.install_from_folder()
            if self.config.enable_driver_update:
                report["updated"] = self.update_all()
            else:
                self.log.info("Автообновление драйверов отключено в конфигурации.")
        except Exception as exc:
            self.log.exception("Неожиданная ошибка DriverManager.run: %s", exc)
        return report

@echo off
rem Регистрация задач PC Optimizer Pro в Планировщике заданий Windows.
rem Запуск:  install_scheduled_task.bat [--dry-run]
rem   --dry-run  только проверить генерацию XML (без прав администратора).
setlocal
chcp 866 >nul 2>&1
cd /d "%~dp0"

set "DRYRUN="
if /i "%~1"=="--dry-run" set "DRYRUN=1"
if /i "%~1"=="/dry-run" set "DRYRUN=1"
if defined DRYRUN goto run_dry

call :check_admin
if errorlevel 1 (
    echo Запрос прав администратора...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Установка задач PC Optimizer Pro...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_scheduled_task.ps1"
if errorlevel 1 (
    echo.
    echo ОШИБКА установки задач. Смотрите вывод выше и logs\app.log
)
echo.
echo Зарегистрированные задачи:
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0show_scheduled_tasks.ps1"
pause
exit /b 0

:run_dry
echo Проверка в режиме dry-run: задачи не создаются, права администратора не нужны.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_scheduled_task.ps1" -DryRun
echo.
pause
exit /b 0

rem ============================================================
rem  Проверка прав администратора
rem  fltmc не зависит от службы Server (в отличие от net session)
rem ============================================================
:check_admin
fltmc >nul 2>&1
if not errorlevel 1 exit /b 0
net session >nul 2>&1
if not errorlevel 1 exit /b 0
exit /b 1

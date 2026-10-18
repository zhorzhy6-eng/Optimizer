@echo off
rem Удаление или проверка задач "PC Optimizer Pro" в Планировщике заданий.
rem Запуск:  uninstall_scheduled_task.bat [--status]
rem   --status  только показать состояние задач (без прав администратора).
setlocal
chcp 866 >nul 2>&1
cd /d "%~dp0"

if /i "%~1"=="--status" goto show_status

call :check_admin
if errorlevel 1 (
    echo Запрос прав администратора...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Удаление задач PC Optimizer Pro...
schtasks /Delete /TN "PC Optimizer Pro (Light)" /F 2>nul
schtasks /Delete /TN "PC Optimizer Pro (Full)" /F 2>nul
schtasks /Delete /TN "PC Optimizer Pro" /F 2>nul
schtasks /Delete /TN "PC Optimizer Pro (Power Agent)" /F 2>nul

echo.
echo Проверка (пусто = задач не осталось):
schtasks /Query /TN "PC Optimizer Pro (Light)" /FO LIST 2>nul | findstr /C:"TaskName"
schtasks /Query /TN "PC Optimizer Pro (Full)" /FO LIST 2>nul | findstr /C:"TaskName"
schtasks /Query /TN "PC Optimizer Pro" /FO LIST 2>nul | findstr /C:"TaskName"
schtasks /Query /TN "PC Optimizer Pro (Power Agent)" /FO LIST 2>nul | findstr /C:"TaskName"
echo.
echo Готово.
pause
exit /b 0

:show_status
echo Состояние задач PC Optimizer Pro:
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0show_scheduled_tasks.ps1"
echo Готово.
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

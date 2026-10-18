@echo off
rem Ручной запуск PC Optimizer Pro от имени администратора.
rem Аргументы передаются в программу (например: run_admin.bat --once).
setlocal
chcp 866 >nul 2>&1
cd /d "%~dp0"

call :check_admin
if errorlevel 1 (
    echo Запрос прав администратора...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b
)

python -m src.main %*
if errorlevel 1 (
    echo.
    echo Программа завершилась с ошибкой. Подробности в logs\app.log
    pause
)
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

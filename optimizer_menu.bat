@echo off
rem ============================================================
rem  PC Optimizer Pro - интерактивное меню управления
rem  Запуск: двойной клик или из cmd. Требует прав администратора.
rem  Все действия дублируются в logs\menu.log
rem ============================================================
rem Файл сохранён в OEM-кодировке (cp866): так cmd корректно читает русский текст.
rem Консоль переключаем на 866 только при необходимости: chcp забирает stdin,
rem поэтому при автоматизации переключение отключается переменной OPTIMIZER_SKIP_CHCP=1.
if not "%OPTIMIZER_SKIP_CHCP%"=="1" call :ensure_cp
setlocal EnableExtensions EnableDelayedExpansion
title PC Optimizer Pro - Меню управления
cd /d "%~dp0"

set "ROOT=%~dp0"
set "LOGDIR=%ROOT%logs"
set "MENULOG=%LOGDIR%\menu.log"
set "TASKNAME=PC Optimizer Pro"
set "EMPTYCOUNT=0"

if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1

rem ---------- Проверка прав администратора ----------
call :check_admin
if not errorlevel 1 goto admin_ok
if /i "%OPTIMIZER_NO_UAC%"=="1" goto admin_ok

echo Запрос прав администратора...
call :log "Запрос прав администратора (UAC)"
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0

:admin_ok
call :log "Меню запущено от администратора"

rem ---------- Проверка окружения ----------
where python >nul 2>&1
if errorlevel 1 goto no_python
if not exist "%ROOT%src\main.py" goto no_main
call :log "Окружение проверено: python найден, src\main.py найден"

rem ============================================================
rem  Главное меню
rem ============================================================
:show_menu
cls
echo ============================================
echo    PC Optimizer Pro - Меню управления
echo ============================================
echo [1] Поверхностная чистка (быстро)
echo [2] Глубокая оптимизация (полная)
echo [3] Настройка планировщика
echo [4] Показать последний отчёт
echo [5] Выход
echo [6] Настройка расписания и режимов
echo ============================================
set "MENUCHOICE="
set /p "MENUCHOICE=Выберите пункт (1-6): "
if not defined MENUCHOICE (
    set /a EMPTYCOUNT+=1
    if !EMPTYCOUNT! GEQ 3 goto do_exit
    goto show_menu
)
set "EMPTYCOUNT=0"
if "%MENUCHOICE%"=="1" goto run_light
if "%MENUCHOICE%"=="2" goto run_full
if "%MENUCHOICE%"=="3" goto scheduler_menu
if "%MENUCHOICE%"=="4" goto show_report
if "%MENUCHOICE%"=="5" goto do_exit
if "%MENUCHOICE%"=="6" goto settings_menu
echo Неверный пункт: %MENUCHOICE%
call :log "Неверный ввод в главном меню: %MENUCHOICE%"
timeout /t 1 >nul 2>&1
goto show_menu

rem ============================================================
rem  1. Поверхностная чистка: только модуль очистки
rem ============================================================
:run_light
cls
echo === Поверхностная чистка (только очистка мусора) ===
echo.
call :log "Запуск: python -m src.main --light"
python -m src.main --light
set "RC=!ERRORLEVEL!"
call :log "Поверхностная чистка завершена, код !RC!"
echo.
if not "!RC!"=="0" echo [ВНИМАНИЕ] Программа вернула код !RC!. Подробности в logs\app.log
echo Готово. Журнал: logs\app.log
echo.
pause
goto show_menu

rem ============================================================
rem  2. Глубокая оптимизация: полный цикл из 5 шагов
rem ============================================================
:run_full
cls
echo === Глубокая оптимизация (полный цикл) ===
echo.
call :log "Запуск: python -m src.main --once"
python -m src.main --once
set "RC=!ERRORLEVEL!"
call :log "Глубокая оптимизация завершена, код !RC!"
echo.
if not "!RC!"=="0" echo [ВНИМАНИЕ] Программа вернула код !RC!. Подробности в logs\app.log
echo Готово. Журнал: logs\app.log
echo.
pause
goto show_menu

rem ============================================================
rem  4. Последний отчёт
rem ============================================================
:show_report
cls
echo === Последний отчёт ===
echo.
call :log "Просмотр последнего отчёта"
python -m src.main --report
set "RC=!ERRORLEVEL!"
call :log "Просмотр отчёта завершён, код !RC!"
echo.
pause
goto show_menu

rem ============================================================
rem  3. Подменю планировщика
rem ============================================================
:scheduler_menu
cls
echo --- Настройка планировщика ---
echo [1] Установить задачу (время из config\settings.yaml)
echo [2] Удалить задачу
echo [3] Показать статус задачи
echo [4] Изменить время запуска
echo [5] Агент питания (запуск/остановка)
echo [6] Назад
echo ------------------------------
set "SCH="
set /p "SCH=Выберите пункт (1-6): "
if not defined SCH (
    set /a EMPTYCOUNT+=1
    if !EMPTYCOUNT! GEQ 3 goto do_exit
    goto scheduler_menu
)
set "EMPTYCOUNT=0"
if "%SCH%"=="1" goto sched_install
if "%SCH%"=="2" goto sched_delete
if "%SCH%"=="3" goto sched_status
if "%SCH%"=="4" goto sched_time
if "%SCH%"=="5" goto sched_agent
if "%SCH%"=="6" goto show_menu
echo Неверный пункт: %SCH%
call :log "Неверный ввод в меню планировщика: %SCH%"
timeout /t 1 >nul 2>&1
goto scheduler_menu

:sched_install
cls
echo === Установка задачи планировщика ===
echo.
call :log "Установка задачи планировщика"
if not exist "%ROOT%install_scheduled_task.ps1" goto missing_ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%install_scheduled_task.ps1"
set "RC=!ERRORLEVEL!"
call :log "Установка задачи завершена, код !RC!"
echo.
if not "!RC!"=="0" echo [ОШИБКА] Не удалось установить задачу, код !RC!
pause
goto scheduler_menu

:sched_delete
cls
echo === Удаление задачи планировщика ===
echo.
call :log "Удаление задачи %TASKNAME%"
schtasks /Delete /TN "%TASKNAME%" /F
set "RC=!ERRORLEVEL!"
call :log "Удаление задачи завершено, код !RC!"
echo.
if not "!RC!"=="0" echo [ВНИМАНИЕ] Задача не найдена или не удалена, код !RC!
pause
goto scheduler_menu

:sched_status
cls
echo === Статус задач PC Optimizer Pro ===
echo.
call :log "Просмотр статуса задач"
if not exist "%ROOT%show_scheduled_tasks.ps1" goto missing_ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%show_scheduled_tasks.ps1"
set "RC=!ERRORLEVEL!"
call :log "Просмотр статуса завершён, код !RC!"
echo.
pause
goto scheduler_menu

:sched_time
cls
echo === Изменение времени запуска ===
echo.
echo Текущие значения в config\settings.yaml:
findstr /R /C:"[0-9][0-9]:[0-9][0-9]" "%ROOT%config\settings.yaml"
echo.
echo Введите времена через запятую, например: 12:00,18:00
set "NEWTIMES="
set /p "NEWTIMES=Новое время: "
if not defined NEWTIMES goto scheduler_menu
call :log "Изменение расписания на !NEWTIMES!"
if not exist "%ROOT%set_schedule_time.ps1" goto missing_ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%set_schedule_time.ps1" -Times "!NEWTIMES!"
set "RC=!ERRORLEVEL!"
if "!RC!"=="0" goto sched_time_ok
echo [ОШИБКА] Не удалось изменить расписание, код !RC!
call :log "Ошибка изменения расписания, код !RC!"
pause
goto scheduler_menu

:sched_time_ok
call :log "Расписание обновлено, пересоздаю задачу планировщика"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%install_scheduled_task.ps1"
echo.
pause
goto scheduler_menu

:sched_agent
cls
echo === Агент питания ===
echo.
call :log "Просмотр агента питания"
if not exist "%ROOT%power_agent_control.ps1" goto missing_ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%power_agent_control.ps1" -Action status
echo.
echo [1] Запустить агент
echo [2] Остановить агент
echo [3] Назад
echo ------------------------------
set "AG="
set /p "AG=Выберите пункт (1-3): "
if not defined AG goto scheduler_menu
call :log "Агент питания, действие: !AG!"
if "%AG%"=="1" powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%power_agent_control.ps1" -Action start
if "%AG%"=="2" powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%power_agent_control.ps1" -Action stop
pause
goto scheduler_menu

:missing_ps1
echo [ОШИБКА] Не найден install_scheduled_task.ps1 / set_schedule_time.ps1
call :log "ОШИБКА: не найден вспомогательный PowerShell-скрипт"
pause
goto scheduler_menu

rem ============================================================
rem  6. Настройка расписания и режимов
rem ============================================================
:settings_menu
cls
echo --- Настройка расписания и режимов ---
echo [1] Настроить времена чисток
echo [2] Настроить режимы энергопотребления
echo [3] Показать текущие настройки
echo [4] Назад
echo ---------------------------------------
set "SETM="
set /p "SETM=Выберите пункт (1-4): "
if not defined SETM (
    set /a EMPTYCOUNT+=1
    if !EMPTYCOUNT! GEQ 3 goto do_exit
    goto settings_menu
)
set "EMPTYCOUNT=0"
if "%SETM%"=="1" goto settings_times
if "%SETM%"=="2" goto settings_power
if "%SETM%"=="3" goto settings_show
if "%SETM%"=="4" goto show_menu
echo Неверный пункт: %SETM%
call :log "Неверный ввод в настройках: %SETM%"
timeout /t 1 >nul 2>&1
goto settings_menu

:settings_times
cls
echo === Настройка времён чисток ===
echo.
echo Текущее расписание (config\settings.yaml):
findstr /R /C:"[0-9][0-9]:[0-9][0-9]" "%ROOT%config\settings.yaml"
echo.
set "LIGHTTIMES="
set /p "LIGHTTIMES=Время поверхностной чистки (HH:MM через запятую, Enter - не менять): "
set "FULLTIMES="
set /p "FULLTIMES=Время глубокой оптимизации (HH:MM через запятую, Enter - не менять): "
if not defined LIGHTTIMES if not defined FULLTIMES goto settings_menu
call :log "Настройка времён: light=!LIGHTTIMES! full=!FULLTIMES!"
if not exist "%ROOT%set_schedule_time.ps1" goto missing_ps1_settings
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%set_schedule_time.ps1" -LightTimes "!LIGHTTIMES!" -FullTimes "!FULLTIMES!"
set "RC=!ERRORLEVEL!"
if "!RC!"=="0" goto settings_times_ok
echo [ОШИБКА] Не удалось обновить расписание, код !RC!
pause
goto settings_menu

:settings_times_ok
call :log "Расписание обновлено, пересоздаю задачи"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%install_scheduled_task.ps1"
echo.
pause
goto settings_menu

:settings_power
cls
echo === Настройка режимов энергопотребления ===
echo.
echo Доступные схемы в системе (powercfg):
powercfg /list
echo.
echo Имена для выбора: high_performance, balanced, power_saver, ultimate
echo.
set "GS="
set /p "GS=Схема для игр (Enter - не менять): "
set "OS="
set /p "OS=Схема для офиса (Enter - не менять): "
set "IS="
set /p "IS=Схема для простоя (Enter - не менять): "
if not defined GS if not defined OS if not defined IS goto settings_menu
call :log "Настройка схем: game=!GS! office=!OS! idle=!IS!"
if not exist "%ROOT%set_power_scheme.ps1" goto missing_ps1_settings
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%set_power_scheme.ps1" -Game "!GS!" -Office "!OS!" -Idle "!IS!"
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" echo [ОШИБКА] Не удалось обновить схемы, код !RC!
echo.
pause
goto settings_menu

:settings_show
cls
echo === Текущие настройки ===
echo.
echo [Расписание] (секция schedule):
findstr /R /C:"[0-9][0-9]:[0-9][0-9]" "%ROOT%config\settings.yaml"
echo.
echo [Энергопотребление] (секция power):
findstr /C:"game_scheme:" /C:"office_scheme:" /C:"idle_scheme:" "%ROOT%config\settings.yaml"
echo.
call :log "Просмотр текущих настроек"
pause
goto settings_menu

:missing_ps1_settings
echo [ОШИБКА] Не найден вспомогательный PowerShell-скрипт.
call :log "ОШИБКА: не найден set_schedule_time.ps1 / set_power_scheme.ps1"
pause
goto settings_menu

rem ============================================================
rem  Выход
rem ============================================================
:do_exit
call :log "Выход из меню"
echo Выход...
timeout /t 1 >nul 2>&1
endlocal
exit /b 0

rem ============================================================
rem  Ошибки окружения
rem ============================================================
:no_python
echo [ОШИБКА] Python не найден в PATH. Установите Python 3.10+.
call :log "ОШИБКА: Python не найден в PATH"
echo.
pause
endlocal
exit /b 1

:no_main
echo [ОШИБКА] Не найден файл src\main.py. Запустите меню из корня проекта.
call :log "ОШИБКА: не найден src\main.py"
echo.
pause
endlocal
exit /b 1

rem ============================================================
rem  Функция логирования: call :log "сообщение"
rem ============================================================
:log
powershell -NoProfile -Command "Add-Content -Path '%MENULOG%' -Value ('[{0}] {1}' -f (Get-Date -Format 'dd.MM.yyyy HH:mm:ss'), '%~1') -Encoding UTF8"
exit /b 0

rem ============================================================
rem  Приведение кодовой страницы консоли к OEM 866
rem ============================================================
:ensure_cp
set "CURCP="
for /f "usebackq tokens=*" %%a in (`powershell -NoProfile -Command "[Console]::OutputEncoding.CodePage"`) do set "CURCP=%%a"
if not "%CURCP%"=="866" chcp 866 >nul 2>&1
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

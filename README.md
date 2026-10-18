# PC Optimizer Pro

Автономная программа для автоматической оптимизации ПК под Windows 10/11:
очистка мусора, управление энергопотреблением, мониторинг процессов,
дефрагментация HDD и управление драйверами — по настраиваемому расписанию
с полным логированием.

> ⚠️ Запускать **от имени администратора** — иначе очистка `C:\Windows\Temp`,
> `pnputil`, `powercfg` и дефрагментация работать не будут.

---

## Структура проекта

```
pc_optimizer/
├── src/
│   ├── __init__.py          # версия пакета
│   ├── __main__.py          # запуск через `python -m src`
│   ├── main.py              # оркестрация шагов, CLI, догоняющий запуск
│   ├── power_agent_main.py  # CLI фонового агента питания
│   │
│   ├── core/                # инфраструктура
│   │   ├── config.py        # загрузка и валидация конфигурации (YAML)
│   │   ├── constants.py     # имена задач, пути и режимы по умолчанию
│   │   ├── logger.py        # логирование с уровнем TRACE
│   │   ├── reporting.py     # текстовые отчёты (формирование, поиск, вывод)
│   │   ├── scheduler.py     # планировщик (обёртка над `scheduler`)
│   │   ├── state.py         # состояние последнего запуска (logs/state.json)
│   │   ├── power_context.py # состояние агента питания (logs/power_context.json)
│   │   └── system/          # системные вызовы Windows
│   │       ├── windows.py   # права администратора, простой, кодовые страницы
│   │       ├── shell.py     # запуск утилит + автоподбор кодировки вывода
│   │       └── safety.py    # общие правила защиты путей
│   │
│   ├── optimization/        # базовые функции (шаги 1–5)
│   │   ├── cleaner.py       # очистка мусора
│   │   ├── process_monitor.py  # мониторинг процессов (psutil)
│   │   ├── power_manager.py    # управление питанием (powercfg)
│   │   ├── defragmenter.py     # дефрагментация (только HDD)
│   │   └── driver_manager.py   # управление драйверами (pnputil/winget)
│   │
│   └── advanced/            # расширенные функции (шаги 6+)
│       ├── startup_manager.py  # автозагрузка: анализ и обратимое отключение
│       ├── service_manager.py  # службы: анализ и смена типа запуска
│       ├── network_tuner.py    # DNS, сброс кэша, TCP-тюнинг (с бэкапом)
│       ├── disk_health.py      # SMART и свободное место (только чтение)
│       ├── duplicate_finder.py # большие файлы и дубликаты
│       ├── winget_updater.py   # обновления winget с откатом
│       ├── thermal_monitor.py  # температура и троттлинг (только чтение)
│       └── power_agent.py      # фоновый агент питания (контекст + гистерезис)
│
├── tests/                   # pytest-тесты для модулей
├── logs/                    # app.log + state.json + power_context.json + отчёты + menu.log
├── config/settings.yaml     # настройки
├── requirements.txt         # зависимости (pip)
├── pyproject.toml           # метаданные пакета и консольная команда
├── pytest.ini               # настройки тестов
├── optimizer_menu.bat       # интерактивное меню (главная точка входа)
├── run_admin.bat            # ручной запуск от администратора
├── install_scheduled_task.bat   # регистрация в Планировщике заданий
├── install_scheduled_task.ps1   # создание задач Light/Full/Power Agent
├── show_scheduled_tasks.ps1     # состояние задач (без прав, не зависит от языка)
├── power_agent_control.ps1      # статус/запуск/остановка агента питания
├── set_schedule_time.ps1        # изменение времён light/full
├── set_power_scheme.ps1         # выбор схемы для игр/офиса/простоя
└── uninstall_scheduled_task.bat # удаление задач (Light, Full, Power Agent и старых)
```

### Слои приложения

| Слой | Пакет | Модули | Ответственность |
|---|---|---|---|
| Ядро | `core` | `config`, `constants`, `logger`, `reporting`, `scheduler`, `state` | конфигурация, логирование, состояние, отчёты, расписание |
| Системный | `core.system` | `windows`, `shell`, `safety` | права, простой, кодовые страницы, запуск утилит, защита путей |
| Оптимизация | `optimization` | `cleaner`, `process_monitor`, `power_manager`, `defragmenter`, `driver_manager` | шаги 1–5 полного цикла |
| Расширения | `advanced` | `startup_manager`, `service_manager`, `network_tuner`, `disk_health`, `duplicate_finder`, `winget_updater`, `thermal_monitor` | шаги 6+ (пункт 4 ТЗ), включаются по флагам |
| Оркестрация | `src` | `main`, `__main__` | порядок шагов, режимы light/full, CLI |
| Интерфейс | — | `optimizer_menu.bat`, `*.ps1` | интерактивное меню и задачи Планировщика Windows |

Правила зависимостей между слоями:

```
main ──▶ optimization ──┐
  │          │          ├──▶ core.system (shell, safety, windows)
  │          ▼          │
  └──▶ advanced ────────┤
             │          ▼
             └──────▶ core (logger, config, constants, reporting, state, scheduler)
```

- зависимости направлены только «вниз»: `advanced`/`optimization` не импортируют
  друг друга, кроме одного разрешённого случая — `advanced.thermal_monitor`
  использует `optimization.power_manager` для реакции на перегрев;
- `core` не зависит ни от `optimization`, ни от `advanced`;
- модуль `main` — единственное место, где собираются все шаги вместе, поэтому
  внутренние импорты шагов выполняются лениво (внутри функций).

Правила, которых придерживается код:
- каждая функция обёрнута в `try/except` и логирует ошибку, но не роняет программу;
- модули не зависят друг от друга напрямую, кроме инфраструктурного слоя;
- консольные утилиты запускаются только через `src/shell.py`;
- системные вызовы Windows — только через `src/system.py`.

---

## Установка

```bat
cd /d E:\Python\Optimizer
python -m pip install -r requirements.txt
```

Требования: **Python 3.10+**, Windows 10/11.

Дополнительно можно установить как пакет (появится команда `pc-optimizer`):

```bat
python -m pip install -e .
pc-optimizer --light
```

---

## Запуск

```bat
:: Интерактивное меню (рекомендуется) — двойной клик или:
optimizer_menu.bat

:: Однократный полный прогон всех задач (полезно для проверки)
python -m src.main --once

:: Поверхностная чистка: только очистка мусора (без питания/процессов/драйверов)
python -m src.main --light
:: То же через --mode
python -m src.main --once --mode light
python -m src.main --once --mode full

:: Показать последний отчёт и выйти
python -m src.main --report

:: Режим планировщика: программа работает в фоне и выполняет задачи
:: в заданное в settings.yaml время
python -m src.main

:: Свой конфигурационный файл и каталог логов
python -m src.main --config config/settings.yaml --log-dir logs

:: Эквивалентный короткий запуск (пакет сам вызывает main)
python -m src --once
```

Либо дважды кликните `run_admin.bat` (запросит права администратора).

---

## Интерактивное меню — `optimizer_menu.bat`

Единая точка входа: при старте проверяет права (при необходимости перезапускается
через `Start-Process -Verb RunAs`), затем показывает меню.

Проверка прав вынесена в подпрограмму `:check_admin` (все `.bat` используют её):
сначала `fltmc` — он требует прав администратора и **не зависит от службы Server**,
затем резервная проверка `net session`. Так меню не уходит в цикл UAC на машинах,
где служба Server отключена.

```
============================================
   PC Optimizer Pro - Меню управления
============================================
[1] Поверхностная чистка (быстро)
[2] Глубокая оптимизация (полная)
[3] Настройка планировщика
[4] Показать последний отчёт
[5] Выход
[6] Настройка расписания и режимов
============================================
```

| Пункт | Действие |
|---|---|
| 1 | `python -m src.main --light` — только очистка: `%TEMP%`, `C:\Windows\Temp`, корзина, старые логи |
| 2 | `python -m src.main --once` — полный цикл из 5 шагов (очистка, процессы, питание, дефрагментация, драйверы) |
| 3 | подменю планировщика: установить задачу, удалить, показать статус, изменить время |
| 4 | `python -m src.main --report` — вывод последнего `logs/report_*.txt` |
| 5 | выход |
| 6 | подменю: времена чисток, схемы энергопотребления, просмотр настроек |

Подменю планировщика (пункт 3):

| Подпункт | Действие |
|---|---|
| 1 | установка задач `PC Optimizer Pro (Light)` и `PC Optimizer Pro (Full)` |
| 2 | удаление задач `schtasks /Delete /TN "PC Optimizer Pro (Light|Full)" /F` |
| 3 | `schtasks /Query /TN "PC Optimizer Pro" /V /FO LIST` |
| 4 | переход к настройке времён чисток (см. пункт 6) |
| 5 | назад |

Подменю настроек (пункт 6):

| Подпункт | Действие |
|---|---|
| 1 | задать времена поверхностной (light) и глубокой (full) чистки → `set_schedule_time.ps1` → пересоздание задач |
| 2 | выбрать схему для игр/офиса/простоя → `set_power_scheme.ps1` |
| 3 | показать текущие значения `settings.yaml` |
| 4 | назад |

Каждое действие дублируется в `logs/menu.log`. Защита от зацикливания: три пустых
ввода подряд завершают меню.

### Переменные окружения меню

| Переменная | Назначение |
|---|---|
| `OPTIMIZER_SKIP_CHCP=1` | не переключать кодовую страницу консоли (нужно при автоматизации через перенаправление ввода) |
| `OPTIMIZER_NO_UAC=1` | не запрашивать повышение прав (для отладки) |

---

## Автономный запуск через Планировщик заданий Windows

Запустите `install_scheduled_task.bat` (от администратора). Он создаёт **две
отдельные задачи** на основе `config/settings.yaml`:

- `PC Optimizer Pro (Light)` — поверхностная чистка (`--mode light`) в `light_times`;
- `PC Optimizer Pro (Full)` — полная оптимизация (`--mode full`) в `full_times`.

Для каждой задачи включён `StartWhenAvailable` — пропущенный запуск выполнится
сразу после включения ПК. Задача старой версии `PC Optimizer Pro` (без суффикса)
при установке удаляется.

### Проверка и диагностика

| Команда | Что делает |
|---|---|
| `install_scheduled_task.bat --dry-run` | генерирует и проверяет XML задач, **ничего не создаёт** и не требует прав |
| `uninstall_scheduled_task.bat --status` | показывает состояние задач (Status, Next Run Time, Last Run Time, Last Result, уровень прав) без прав |
| `show_scheduled_tasks.ps1` | то же, что `--status`, напрямую (используется меню, пункт 3.3) |
| `install_scheduled_task.bat` | создаёт/пересоздаёт задачи (нужны права администратора) |
| `uninstall_scheduled_task.bat` | удаляет обе задачи и задачу старого формата |

Состояние задач читается через `Get-ScheduledTask` / `Get-ScheduledTaskInfo`, а не
разбором текста `schtasks`: при кодовой странице 866 `schtasks` печатает
локализованные заголовки («Имя задачи:»), из-за чего фильтрация по английским
строкам не находила ни одной строки.

Перед созданием задач `install_scheduled_task.ps1` проверяет, что команда
`python -m src.main` действительно запускается в каталоге проекта, и только после
этого регистрирует задачи — так исключается «задача есть, но не работает».

Особенности шаблона задачи:

- `<Command>` берётся в кавычки (корректно и для путей с пробелами);
- `RunLevel = HighestAvailable` — задача запускается с повышением прав;
- `LogonType = InteractiveToken` — запуск под текущим пользователем, поэтому
  задача выполняется, когда пользователь вошёл в систему; пропущенное время
  компенсируется через `StartWhenAvailable`;
- `ExecutionTimeLimit = PT6H` — полный цикл с дефрагментацией HDD может идти долго;
- `MultipleInstancesPolicy = IgnoreNew` — второй экземпляр не запускается.

Проверить напрямую: `schtasks /Query /TN "PC Optimizer Pro (Light)" /V /FO LIST`.
Удалить: `uninstall_scheduled_task.bat`.

Пустые списки в конфиге (`light_times: []`) означают «задачу не создавать» —
соответствующая задача будет удалена при следующем запуске установщика.

---

## Конфигурация — `config/settings.yaml`

Основные секции:

| Секция | Параметр | Описание |
|---|---|---|
| `schedule` | `light_times` | времена поверхностной чистки (`--mode light`) |
| `schedule` | `full_times` | времена глубокой оптимизации (`--mode full`) |
| `schedule` | `times` | устаревший формат (обратная совместимость: все запуски = full) |
| `schedule` | `catch_up_on_wake` | догоняющий запуск пропущенных задач |
| `cleaner` | `temp_paths` | каталоги для очистки (`%TEMP%`, `C:\Windows\Temp`) |
| `cleaner` | `clean_recycle_bin` | очищать корзину |
| `cleaner` | `log_retention_days` | удалять логи старше N дней |
| `process_monitor` | `cpu_threshold_percent` / `ram_threshold_percent` | пороги «тяжёлых» процессов |
| `process_monitor` | `idle_minutes` | простой пользователя до закрытия нежелательных процессов |
| `process_monitor` | `unwanted_processes` | процессы, разрешённые к закрытию при простое |
| `power` | `game_scheme` / `office_scheme` / `idle_scheme` | схема питания для игр/офиса/простоя |
| `power` | `game_processes` | процессы игр → `game_scheme` |
| `power` | `office_processes` | офисные процессы → `office_scheme` |
| `power` | `schemes` | GUID схем питания (в т.ч. `ultimate`) |
| `defrag` | `drives` | диски для анализа/дефрагментации |
| `drivers` | `driver_folder` | папка с подготовленными `.inf` |
| `drivers` | `enable_driver_update` / `update_tool` | автообновление (`winget`/`uso`) |
| `logging` | `level` / `dir` / `generate_report` | уровень, каталог, отчёт |

---

## Поведение модулей

### 1. Очистка мусора (`cleaner`)
Удаляет файлы и подкаталоги из `%TEMP%`, `C:\Windows\Temp`, очищает корзину
(`Clear-RecycleBin`), удаляет ротированные логи старше `log_retention_days` дней.
Занятые файлы пропускаются и логируются — программа не падает.

### 2. Мониторинг процессов (`process_monitor`)
Собирает CPU/RAM через `psutil`, помечает «тяжёлые» процессы по порогам.
Закрывает **только** процессы из `unwanted_processes` и только если пользователь
неактивен дольше `idle_minutes` (idle определяется через `GetLastInputInfo`).

### 3. Энергопотребление (`power_manager`)
Схема для каждого сценария настраивается в `power` (`game_scheme`, `office_scheme`,
`idle_scheme`):
- игра (процесс из `game_processes`) → `game_scheme` (по умолчанию «Высокая производительность»);
- офис (`office_processes`) → `office_scheme` (по умолчанию «Сбалансированная»);
- иначе (простой) → `idle_scheme` (по умолчанию «Экономия энергии»).

Доступные схемы: `high_performance`, `balanced`, `power_saver`, `ultimate`
(Ultimate Performance есть не на всех ПК — при недоступности программа откатится
на `high_performance`). Переключение через `powercfg /setactive <GUID>`.

### 4. Дефрагментация (`defragmenter`)
Определяет тип носителя через PowerShell (`Get-PhysicalDisk.MediaType`).
Анализ — `defrag.exe C: /A /V /U`. Дефрагментация запускается **только для HDD**;
для SSD и дисков с неопределённым типом операция пропускается.

### 5. Драйверы (`driver_manager`)
- установка из папки: `pnputil /add-driver "*.inf" /install`;
- удаление: `pnputil /delete-driver oem0.inf /force`;
- просмотр: `pnputil /enum-drivers`;
- автообновление: `winget upgrade --all` или `UsoClient ScanInstallWait`.

Загрузка с сайтов производителей не автоматизируется (нет API) — только
подготовленная папка или winget.

---

## Расширенные функции (шаги 6+)

Подключаются флагами в `settings.yaml`. **По умолчанию выполняются только
безопасные, читающие модули**, а всё, что меняет систему, выключено.

| Модуль | Секция | По умолчанию | Что делает |
|---|---|---|---|
| `startup_manager` | `startup` | анализ включён | читает реестр `Run`/`RunOnce` (HKCU/HKLM/Wow6432Node) и папки «Автозагрузка» |
| `service_manager` | `services` | выключен | список служб; перевод в ручной запуск — только по списку и только не критичных |
| `network_tuner` | `network` | выключен | сброс DNS-кэша, смена DNS, TCP-тюнинг (с сохранением прежних значений) |
| `disk_health` | `disk_health` | включён | SMART-состояние дисков, свободное место, предупреждения |
| `duplicate_finder` | `duplicates` | выключен | большие файлы и дубликаты по SHA-256 |
| `winget_updater` | `winget` | выключен | список доступных обновлений; установка — только при `upgrade_all: true` |
| `thermal_monitor` | `thermal` | включён | температура и признак троттлинга; реакция схемой питания — по флагу |

### Меры безопасности

- **Обратимость.** Отключение записи автозагрузки переносит её в резервный ключ
  `<Run>_disabled_by_optimizer` (или в подпапку `disabled` для файлов), службы —
  сохраняют прежний тип запуска в `logs/services_backup.json`, DNS и TCP —
  в `logs/network_backup.json`, пакеты winget — в `logs/winget_backup.json`.
  Вернуть изменения можно методами `enable_entry()`, `restore_services()`,
  `restore_dns()`, `rollback()`.
- **Защита критичного.** Службы из встроенного списка (`RpcSs`, `DcomLaunch`,
  `Power`, `PlugPlay`, `Winmgmt`, `EventLog`, сеть, обновления и др.) не
  изменяются даже при явном указании в конфиге — они попадают в отчёт как
  `skipped_protected`.
- **Защита путей.** Общий модуль `safety` запрещает работу с корнями дисков,
  `Windows`, `Program Files`, `ProgramData`, профилем пользователя и личными
  папками. Используется очисткой и поиском дубликатов.
- **Лимиты.** `duplicates.max_files` ограничивает сканирование,
  `duplicates.delete_duplicates: false` означает «только отчёт»,
  удаление всегда оставляет самую старую копию.

### Пример включения

```yaml
startup:
  enabled: true
  disable_entries: ["SomeUpdater"]

network:
  enabled: true
  flush_dns: true
  set_dns: true
  dns_servers: ["1.1.1.1", "8.8.8.8"]

duplicates:
  enabled: true
  scan_paths: ["%USERPROFILE%\\Downloads"]
  min_size_mb: 50
  delete_duplicates: false   # сначала посмотрите отчёт
```

Шаги 6+ попадают в общий отчёт (`logs/report_*.txt`) отдельными секциями
(`[Автозагрузка]`, `[Здоровье дисков]`, `[Температура]` и т. д.).

---

## Агент питания (power_agent)

Фоновый агент, который **постоянно** следит за контекстом и переключает схему
электропитания сразу, а не только во время прогона по расписанию: запустили
игру в 15:00 — схема сменится на «Высокая производительность» в течение
`interval_seconds`, закрыли игру — через `game_cooldown_seconds` вернётся
обратно.

### Как работает

Каждые `interval_seconds` (по умолчанию 10) агент собирает процессы и
классифицирует контекст по правилам:

| Приоритет | Контекст | Условие |
|---|---|---|
| 1 | `game` | процесс из `power.game_processes` **и** пользователь активен (idle < 120 с) |
| 2 | `heavy` | процесс из `power.heavy_task_processes` с CPU ≥ 50 % |
| 3 | `office` | процесс из `power.office_processes` и пользователь активен |
| 4 | `idle` | пользователь неактивен дольше `process_monitor.idle_minutes` |
| 5 | fallback | ничего не найдено — текущий контекст сохраняется, схема не трогается |

Лаунчеры из `power.launchers_to_ignore` (steam.exe и т.п.) сами по себе игру
не включают. Гистерезис: переход **из** игры — не раньше
`power_agent.game_cooldown_seconds` (по умолчанию 180 с), переход **в** игру —
сразу; защита от «дрожания» — при более чем 3 переключениях за минуту агент
пропускает смену схемы и пишет предупреждение.

Состояние агента хранится в `logs/power_context.json` (текущий контекст,
схема, история последних 20 переключений; запись атомарная).

### Настройка (`config/settings.yaml`)

```yaml
power_agent:
  enabled: false            # включите, чтобы агент работал
  interval_seconds: 10
  game_cooldown_seconds: 180
  context_map:
    game: "high_performance"
    heavy: "high_performance"
    office: "balanced"
    idle: "power_saver"

power:
  launchers_to_ignore: ["steam.exe", "epicgameslauncher.exe", "battle.net.exe"]
  heavy_task_processes: ["blender.exe", "ffmpeg.exe", "cl.exe"]
```

### Запуск

```bat
:: отдельным процессом (окно свёрнуто, реагирует на Ctrl+C/SIGTERM)
python -m src.power_agent_main --config config/settings.yaml

:: или из меню: [3] Настройка планировщика -> [5] Агент питания
:: (статус/запуск/остановка через power_agent_control.ps1)
```

При `install_scheduled_task.bat` создаётся задача
**«PC Optimizer Pro (Power Agent)»** с триггером *At log on* (запуск при входе
в систему), `RunLevel HighestAvailable`, без ограничения времени выполнения —
только если `power_agent.enabled: true`.

Если агент не запущен отдельной задачей, а `power_agent.enabled: true`, то
`python -m src.main` (режим планировщика) сам регистрирует периодический tick
агента — поведение программы при `enabled: false` не меняется.

Агент не закрывает процессы — только переключает схему питания.

---

## Логирование

Единый файл `logs/app.log` с ротацией (5 МБ × 3 файла). Уровень **TRACE** (ниже
DEBUG) для детальной отладки; каждый модуль пишет в свой логгер вида
`pc_optimizer.<module>`.

При `logging.generate_report: true` после каждого цикла пишется текстовый отчёт
`logs/report_YYYYMMDD_HHMMSS.txt`.

---

## Кодировки файлов (важно при редактировании)

| Файлы | Кодировка | Почему |
|---|---|---|
| `*.bat` | **OEM cp866** + переводы строк **CRLF** | cmd.exe не понимает LF (команды перестают распознаваться) и плохо переносит UTF-8 внутри `.bat`. При правке сохраняйте cp866/CRLF, например: `python -c "import pathlib;p=pathlib.Path('optimizer_menu.bat');p.write_bytes(p.read_text(encoding='cp866').encode('cp866'))"` |
| `*.ps1` | **UTF-8 с BOM** | Windows PowerShell 5.1 читает `.ps1` без BOM как ANSI и падает на русском тексте |
| `*.py`, `*.yaml`, `*.md` | UTF-8 (BOM допустим) | `settings.yaml` читается как `utf-8-sig` |

`optimizer_menu.bat` определяет кодовую страницу консоли через
`[Console]::OutputEncoding.CodePage` и вызывает `chcp 866` только когда это нужно:
русский текст остаётся корректным, а перенаправленный ввод не «съедается».

### Кодировка вывода консольных утилит

`powercfg`, `pnputil`, `defrag`, `winget` печатают текст в кодировке консоли,
которая зависит от родителя: UTF-8 при запуске из Windows Terminal, OEM (cp866)
при запуске Планировщиком. Модуль `src/shell.py` читает вывод байтами и
подбирает кодировку (строгий UTF-8 → OEM/ANSI по «читаемости»), поэтому в
`logs/app.log` нет «кракозябр» ни в одном из сценариев. Прямой вызов
`subprocess.run(..., text=True)` в модулях больше не используется.

---

## Тесты

```bat
python -m pytest
```

Тесты используют моки (`subprocess`, `psutil`) и не выполняют реальных операций
с системой. Всего **115 тестов** (114 проходят, 1 пропускается — симлинки требуют
привилегии `SeCreateSymbolicLink`). Покрытие по модулям: `config`, `constants`,
`cleaner`, `process_monitor`, `scheduler`, `power_manager`, `defragmenter`,
`driver_manager`, `shell` (кодировки вывода), `system` (админ/простой/кодовые
страницы), `state`, `reporting` и точка входа `main` (флаги
`--light`/`--report`/`--mode light|full`, догоняющий запуск, отсутствие двойного
прогона).

---

## Риски и принятые меры

| Риск | Решение |
|---|---|
| Закрытие нужных процессов | Закрываются только явно перечисленные `unwanted_processes` |
| Дефрагментация SSD | Обязательная проверка `MediaType` перед запуском |
| Нет прав администратора | Проверка `IsUserAnAdmin()` при старте + предупреждение |
| Не все драйверы обновляются через winget | Установка из папки + уведомления в логе |
| ПК спит в момент запуска | `catch_up_on_wake` + `StartWhenAvailable` в задаче Windows |

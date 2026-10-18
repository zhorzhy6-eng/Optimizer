<#
.SYNOPSIS
    Создаёт задачи PC Optimizer Pro в Планировщике заданий Windows.

.DESCRIPTION
    Создаёт две отдельные задачи:
      - "PC Optimizer Pro (Light)" — поверхностная чистка (--mode light)
      - "PC Optimizer Pro (Full)"  — полная оптимизация (--mode full)
    Времена берутся из config\settings.yaml (light_times / full_times).
    Обратная совместимость: если списков нет, старый ключ times -> full,
    а при полном отсутствии расписания используются 12:00 и 18:00.

    Явно пустые списки (light_times: []) означают «задачу не создавать» —
    соответствующая задача удаляется.

.PARAMETER DryRun
    Только сгенерировать и проверить XML задач, ничего не создавая.
    Права администратора не требуются.

.PARAMETER XmlOutputDir
    Каталог для файлов XML в режиме -DryRun (по умолчанию — временный каталог).
#>
param(
    [switch]$DryRun,
    [string]$XmlOutputDir = $env:TEMP
)

$ErrorActionPreference = "Stop"

$WorkDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Config  = Join-Path $WorkDir "config\settings.yaml"

$TaskLight = "PC Optimizer Pro (Light)"
$TaskFull  = "PC Optimizer Pro (Full)"
$TaskLegacy = "PC Optimizer Pro"
$TaskAgent = "PC Optimizer Pro (Power Agent)"

# --- Проверка прав администратора (в режиме -DryRun не нужна) ---
if (-not $DryRun) {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "ERROR: требуются права администратора (запустите optimizer_menu.bat)." -ForegroundColor Red
        exit 1
    }
}

$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) {
    Write-Host "ERROR: Python не найден в PATH. Установите Python 3.10+ и добавьте в PATH." -ForegroundColor Red
    exit 1
}

# --- Проверяем, что команда, которую будут запускать задачи, действительно работает ---
Push-Location $WorkDir
try {
    $probe = & $PythonExe -m src.main --help 2>&1
    $probeCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($probeCode -ne 0) {
    Write-Host "ERROR: команда 'python -m src.main' в каталоге $WorkDir не работает (код $probeCode)." -ForegroundColor Red
    $probe | Select-Object -First 5 | ForEach-Object { Write-Host "  $_" }
    exit 1
}
Write-Host "Команда запуска работоспособна: $PythonExe -m src.main" -ForegroundColor Green

# --- Читаем времена из settings.yaml ---
$lightTimes = @()
$fullTimes = @()
$legacyTimes = @()
$hasLight = $false
$hasFull = $false
$inSchedule = $false
$currentKey = ""

if (Test-Path $Config) {
    foreach ($line in [System.IO.File]::ReadAllLines($Config)) {
        if ($line -match '^\s*schedule\s*:') { $inSchedule = $true; $currentKey = ""; continue }
        if (-not $inSchedule) { continue }
        if ($line -match '^\S') { break }  # конец секции schedule

        if ($line -match '^\s+(\w+)\s*:') {
            $currentKey = $matches[1]
            if ($currentKey -eq 'light_times') { $hasLight = $true }
            if ($currentKey -eq 'full_times')  { $hasFull = $true }
            continue
        }
        if ($line -match '^\s+-\s*"(\d{1,2}:\d{2}(?::\d{2})?)"') {
            switch ($currentKey) {
                'times'       { $legacyTimes += $matches[1] }
                'light_times' { $lightTimes += $matches[1] }
                'full_times'  { $fullTimes += $matches[1] }
            }
        }
    }
}

if (-not $hasLight -and -not $hasFull) {
    # Обратная совместимость: старый формат times -> полный цикл.
    if ($legacyTimes.Count -gt 0) {
        $fullTimes = $legacyTimes
    } else {
        $fullTimes = @("12:00", "18:00")
    }
    $hasFull = $true
}

# --- Читаем power_agent.enabled из settings.yaml ---
$agentEnabled = $false
$inAgent = $false
if (Test-Path $Config) {
    foreach ($line in [System.IO.File]::ReadAllLines($Config)) {
        if ($line -match '^\s*power_agent\s*:') { $inAgent = $true; continue }
        if ($inAgent -and $line -match '^\S') { break }
        if ($inAgent -and $line -match '^\s*enabled\s*:\s*(true|false)') {
            $agentEnabled = ($matches[1] -eq 'true')
        }
    }
}

function New-TriggerXml([string[]]$Times) {
    $triggers = ""
    foreach ($t in $Times) {
        $hhmm = $t
        if ($hhmm -match '^(\d{1,2}):(\d{2})$') {
            $hhmm = "{0:D2}:{1:D2}:00" -f [int]$matches[1], [int]$matches[2]
        }
        $triggers += @"
    <CalendarTrigger>
      <StartBoundary>2020-01-01T$hhmm</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
"@
    }
    return $triggers
}

function New-TaskXml([string]$Description, [string[]]$Times, [string]$Mode) {
    $triggers = New-TriggerXml $Times
    # Кавычки вокруг Command обязательны, если путь к Python содержит пробелы.
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>$Description</Description>
  </RegistrationInfo>
  <Triggers>
$triggers
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT6H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"$PythonExe"</Command>
      <Arguments>-m src.main --once --mode $Mode --config "config\settings.yaml"</Arguments>
      <WorkingDirectory>$WorkDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

# Тихий вызов schtasks /Delete (не падает при отсутствии задачи).
function Remove-TaskQuiet([string]$Name) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    schtasks /Delete /TN $Name /F 2>&1 | Out-Null
    $ErrorActionPreference = $prev
}

function New-AgentTaskXml([string]$Description) {
    # Задача фонового агента питания: триггер At log on, без ограничения
    # времени выполнения (агент работает постоянно).
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>$Description</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"$PythonExe"</Command>
      <Arguments>-m src.power_agent_main --config "config\settings.yaml"</Arguments>
      <WorkingDirectory>$WorkDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

function Create-Task([string]$Name, [string]$Description, [string[]]$Times, [string]$Mode) {
    $xml = New-TaskXml $Description $Times $Mode
    $tempXml = Join-Path $env:TEMP ("pc_optimizer_task_" + [guid]::NewGuid().ToString("N") + ".xml")
    $xml | Out-File -FilePath $tempXml -Encoding Unicode
    schtasks /Create /TN $Name /XML $tempXml /F | Out-Null
    $rc = $LASTEXITCODE
    Remove-Item $tempXml -ErrorAction SilentlyContinue
    if ($rc -ne 0) {
        Write-Host "ERROR: schtasks /Create для '$Name' вернул код $rc — задача не создана." -ForegroundColor Red
        exit $rc
    }
    Write-Host "Задача '$Name' зарегистрирована. Времена: $($Times -join ', ')" -ForegroundColor Green
}

# --- План: какие задачи должны существовать ---
$tasks = @()
if ($hasLight -and $lightTimes.Count -gt 0) {
    $tasks += [pscustomobject]@{
        Name        = $TaskLight
        Description = "PC Optimizer Pro - поверхностная чистка (очистка мусора)"
        Mode        = "light"
        Times       = $lightTimes
    }
}
if ($hasFull -and $fullTimes.Count -gt 0) {
    $tasks += [pscustomobject]@{
        Name        = $TaskFull
        Description = "PC Optimizer Pro - полная оптимизация (5 шагов и расширенные проверки)"
        Mode        = "full"
        Times       = $fullTimes
    }
}

# --- Режим проверки: только генерация и валидация XML ---
if ($DryRun) {
    Write-Host "=== Режим -DryRun: задачи не создаются ===" -ForegroundColor Yellow
    if (-not (Test-Path $XmlOutputDir)) { New-Item -ItemType Directory -Path $XmlOutputDir -Force | Out-Null }

    if ($tasks.Count -eq 0) {
        Write-Host "  Расписание пустое: задачи Light и Full создаваться не будут."
    }
    foreach ($task in $tasks) {
        $xml = New-TaskXml $task.Description $task.Times $task.Mode
        try {
            [xml]$parsed = $xml
            if (-not $parsed.Task.Actions.Exec.Command) { throw "в XML нет команды задачи" }
        } catch {
            Write-Host "ERROR: некорректный XML для '$($task.Name)': $_" -ForegroundColor Red
            exit 1
        }
        $path = Join-Path $XmlOutputDir ("pc_optimizer_task_" + $task.Mode + ".xml")
        $xml | Out-File -FilePath $path -Encoding Unicode
        Write-Host "  $($task.Name): времена $($task.Times -join ', ') -> $path"
    }

    if ($agentEnabled) {
        $xml = New-AgentTaskXml "PC Optimizer Pro - фоновый агент питания (запуск при входе)"
        try {
            [xml]$parsed = $xml
            if (-not $parsed.Task.Actions.Exec.Command) { throw "в XML нет команды задачи" }
        } catch {
            Write-Host "ERROR: некорректный XML для '$TaskAgent': $_" -ForegroundColor Red
            exit 1
        }
        $path = Join-Path $XmlOutputDir "pc_optimizer_task_power_agent.xml"
        $xml | Out-File -FilePath $path -Encoding Unicode
        Write-Host "  $TaskAgent`: триггер At log on -> $path"
    } else {
        Write-Host "  $TaskAgent`: выключен (power_agent.enabled=false) — задача не создаётся."
    }

    Write-Host "Проверка завершена успешно (права администратора не требовались)." -ForegroundColor Green
    exit 0
}

# --- Миграция: удаляем задачу старой версии с одинарным именем ---
Remove-TaskQuiet $TaskLegacy

# --- Создаём нужные задачи и убираем лишние ---
$lightTask = $tasks | Where-Object { $_.Mode -eq 'light' }
$fullTask  = $tasks | Where-Object { $_.Mode -eq 'full' }

if ($lightTask) {
    Create-Task $lightTask.Name $lightTask.Description $lightTask.Times $lightTask.Mode
} else {
    Remove-TaskQuiet $TaskLight
}
if ($fullTask) {
    Create-Task $fullTask.Name $fullTask.Description $fullTask.Times $fullTask.Mode
} else {
    Remove-TaskQuiet $TaskFull
}

# --- Задача фонового агента питания (только если включён в конфиге) ---
if ($agentEnabled) {
    $agentXml = New-AgentTaskXml "PC Optimizer Pro - фоновый агент питания (запуск при входе)"
    $tempXml = Join-Path $env:TEMP ("pc_optimizer_task_" + [guid]::NewGuid().ToString("N") + ".xml")
    $agentXml | Out-File -FilePath $tempXml -Encoding Unicode
    schtasks /Create /TN $TaskAgent /XML $tempXml /F | Out-Null
    $rc = $LASTEXITCODE
    Remove-Item $tempXml -ErrorAction SilentlyContinue
    if ($rc -ne 0) {
        Write-Host "ERROR: schtasks /Create для '$TaskAgent' вернул код $rc — задача не создана." -ForegroundColor Red
        exit $rc
    }
    Write-Host "Задача '$TaskAgent' зарегистрирована. Триггер: при входе пользователя." -ForegroundColor Green
} else {
    Remove-TaskQuiet $TaskAgent
}

Write-Host "Готово. Пропущенные запуски выполняются при следующем включении ПК (StartWhenAvailable)." -ForegroundColor Green
exit 0

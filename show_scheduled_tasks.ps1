<#
.SYNOPSIS
    Показывает состояние задач PC Optimizer Pro в Планировщике заданий.

.DESCRIPTION
    Использует Get-ScheduledTask / Get-ScheduledTaskInfo (структурированные
    объекты), поэтому вывод не зависит от языка системы — в отличие от
    разбора локализованного текста `schtasks /Query`.
    Права администратора не требуются.
#>
$ErrorActionPreference = "Continue"

$names = @(
    "PC Optimizer Pro (Light)",
    "PC Optimizer Pro (Full)",
    "PC Optimizer Pro (Power Agent)",
    "PC Optimizer Pro"   # задача старого формата, если ещё осталась
)

$found = $false
foreach ($name in $names) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) { continue }

    $found = $true
    $info = Get-ScheduledTaskInfo -TaskName $name -ErrorAction SilentlyContinue

    Write-Host ("[{0}]" -f $name) -ForegroundColor Green
    Write-Host ("   Состояние:        {0}" -f $task.State)
    Write-Host ("   Уровень прав:     {0}" -f $task.Principal.RunLevel)
    Write-Host ("   От имени:         {0}" -f $task.Principal.UserId)
    if ($info) {
        Write-Host ("   Следующий запуск: {0}" -f $info.NextRunTime)
        Write-Host ("   Последний запуск: {0}" -f $info.LastRunTime)
        Write-Host ("   Код результата:   {0}" -f $info.LastTaskResult)
    }

    $times = @()
    foreach ($trigger in $task.Triggers) {
        if ($trigger.StartBoundary) {
            try { $times += ([datetime]$trigger.StartBoundary).ToString("HH:mm") } catch { }
        }
    }
    if ($times.Count -gt 0) {
        Write-Host ("   Времена запуска:  {0}" -f (($times | Sort-Object) -join ", "))
    }

    $action = $task.Actions | Select-Object -First 1
    if ($action) {
        Write-Host ("   Команда:          {0} {1}" -f $action.Execute, $action.Arguments)
        Write-Host ("   Рабочий каталог:  {0}" -f $action.WorkingDirectory)
    }
    Write-Host ""
}

if (-not $found) {
    Write-Host "Задачи PC Optimizer Pro не найдены." -ForegroundColor Yellow
    Write-Host "Установите их: install_scheduled_task.bat (от имени администратора)."
}

exit 0

<#
.SYNOPSIS
    Управление фоновым агентом питания: статус, запуск, остановка.

.PARAMETER Action
    status | start | stop
#>
param(
    [ValidateSet("status", "start", "stop")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$WorkDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-AgentPids {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*power_agent_main*' } |
        Select-Object -ExpandProperty ProcessId
}

switch ($Action) {
    "status" {
        $pids = @(Get-AgentPids)
        if ($pids.Count -gt 0) {
            Write-Host ("Агент питания запущен (PID: {0})." -f ($pids -join ", ")) -ForegroundColor Green
            $contextFile = Join-Path $WorkDir "logs\power_context.json"
            if (Test-Path $contextFile) {
                try {
                    $ctx = Get-Content $contextFile -Raw | ConvertFrom-Json
                    Write-Host ("Контекст: {0} -> {1}" -f $ctx.current, $ctx.scheme)
                } catch { }
            }
        } else {
            Write-Host "Агент питания не запущен." -ForegroundColor Yellow
            Write-Host "Включите его: power_agent.enabled: true в config\settings.yaml."
        }
    }
    "start" {
        $pids = @(Get-AgentPids)
        if ($pids.Count -gt 0) {
            Write-Host ("Агент питания уже запущен (PID: {0})." -f ($pids -join ", ")) -ForegroundColor Green
            exit 0
        }
        $python = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not $python) {
            Write-Host "ERROR: Python не найден в PATH." -ForegroundColor Red
            exit 1
        }
        Start-Process -FilePath $python `
            -ArgumentList "-m", "src.power_agent_main", "--config", "config\settings.yaml" `
            -WorkingDirectory $WorkDir -WindowStyle Minimized
        Write-Host "Агент питания запущен (окно свернуто)." -ForegroundColor Green
    }
    "stop" {
        $pids = @(Get-AgentPids)
        if ($pids.Count -eq 0) {
            Write-Host "Агент питания не запущен." -ForegroundColor Yellow
            exit 0
        }
        foreach ($procId in $pids) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }
        Write-Host "Агент питания остановлен." -ForegroundColor Green
    }
}
exit 0

<#
.SYNOPSIS
    Обновляет времена чисток (light/full) в config\settings.yaml.

.DESCRIPTION
    Заменяет списки light_times и/или full_times в секции schedule.
    Файл сохраняется в UTF-8 без BOM. Задачу планировщика нужно пересоздать
    (это делает optimizer_menu.bat, вызывая install_scheduled_task.ps1).

.EXAMPLE
    powershell -File set_schedule_time.ps1 -LightTimes "12:00" -FullTimes "18:00,20:00"
#>
param(
    [string]$LightTimes = "",
    [string]$FullTimes = ""
)

$ErrorActionPreference = "Stop"

$WorkDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Config = Join-Path $WorkDir "config\settings.yaml"

if (-not (Test-Path -LiteralPath $Config)) {
    Write-Host "ERROR: не найден файл $Config" -ForegroundColor Red
    exit 1
}

function Parse-Times([string]$TimesRaw) {
    $result = @()
    foreach ($t in ($TimesRaw -split ',')) {
        $t = $t.Trim()
        if ($t -eq '') { continue }
        if ($t -notmatch '^(\d{1,2}):(\d{2})(?::(\d{2}))?$') {
            Write-Host "ERROR: некорректное время '$t' (ожидается HH:MM)" -ForegroundColor Red
            exit 1
        }
        $hours = [int]$matches[1]
        $minutes = [int]$matches[2]
        if (($hours -gt 23) -or ($minutes -gt 59)) {
            Write-Host "ERROR: время вне диапазона '$t' (часы 0-23, минуты 0-59)" -ForegroundColor Red
            exit 1
        }
        $result += $t
    }
    return $result
}

$newLight = @()
$newFull = @()
if ($LightTimes -ne "") { $newLight = Parse-Times $LightTimes }
if ($FullTimes -ne "") { $newFull = Parse-Times $FullTimes }
if ($newLight.Count -eq 0 -and $newFull.Count -eq 0) {
    Write-Host "ERROR: задайте хотя бы -LightTimes или -FullTimes" -ForegroundColor Red
    exit 1
}

$lines = [System.IO.File]::ReadAllLines($Config)
$out = New-Object System.Collections.Generic.List[string]
$replacedLight = $false
$replacedFull = $false
$i = 0

while ($i -lt $lines.Count) {
    $line = $lines[$i]
    $mL = [regex]::Match($line, '^(\s*)light_times\s*:\s*$')
    $mF = [regex]::Match($line, '^(\s*)full_times\s*:\s*$')

    if ((-not $replacedLight) -and $mL.Success -and ($newLight.Count -gt 0)) {
        $indent = $mL.Groups[1].Value
        $out.Add($line)
        $j = $i + 1
        while (($j -lt $lines.Count) -and ($lines[$j] -match '^\s*-\s*')) { $j++ }
        foreach ($t in $newLight) { $out.Add("$indent  - `"$t`"") }
        $i = $j
        $replacedLight = $true
        continue
    }
    if ((-not $replacedFull) -and $mF.Success -and ($newFull.Count -gt 0)) {
        $indent = $mF.Groups[1].Value
        $out.Add($line)
        $j = $i + 1
        while (($j -lt $lines.Count) -and ($lines[$j] -match '^\s*-\s*')) { $j++ }
        foreach ($t in $newFull) { $out.Add("$indent  - `"$t`"") }
        $i = $j
        $replacedFull = $true
        continue
    }
    $out.Add($line)
    $i++
}

# Вставка отсутствующих ключей сразу после строки "schedule:"
if (($newLight.Count -gt 0 -and -not $replacedLight) -or
    ($newFull.Count -gt 0 -and -not $replacedFull)) {
    $out2 = New-Object System.Collections.Generic.List[string]
    foreach ($l in $out) {
        $out2.Add($l)
        if ($l -match '^schedule\s*:') {
            if ($newLight.Count -gt 0 -and -not $replacedLight) {
                $out2.Add("  light_times:")
                foreach ($t in $newLight) { $out2.Add("    - `"$t`"") }
                $replacedLight = $true
            }
            if ($newFull.Count -gt 0 -and -not $replacedFull) {
                $out2.Add("  full_times:")
                foreach ($t in $newFull) { $out2.Add("    - `"$t`"") }
                $replacedFull = $true
            }
        }
    }
    $out = $out2
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($Config, $out, $utf8NoBom)

$msg = @()
if ($newLight.Count -gt 0) { $msg += "light: $($newLight -join ', ')" }
if ($newFull.Count -gt 0)  { $msg += "full: $($newFull -join ', ')" }
Write-Host "Расписание обновлено: $($msg -join '; ')" -ForegroundColor Green
exit 0

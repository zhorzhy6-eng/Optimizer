<#
.SYNOPSIS
    Обновляет схемы питания (game_scheme / office_scheme / idle_scheme) в config\settings.yaml.

.DESCRIPTION
    Изменяет, какая схема электропитания применяется для каждого сценария:
    -Game (игры), -Office (офис), -Idle (простой).
    Допустимые имена: high_performance, balanced, power_saver, ultimate.
    Файл сохраняется в UTF-8 без BOM.

.EXAMPLE
    powershell -File set_power_scheme.ps1 -Game "ultimate" -Idle "power_saver"
#>
param(
    [string]$Game = "",
    [string]$Office = "",
    [string]$Idle = ""
)

$ErrorActionPreference = "Stop"

$WorkDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Config = Join-Path $WorkDir "config\settings.yaml"

if (-not (Test-Path -LiteralPath $Config)) {
    Write-Host "ERROR: не найден файл $Config" -ForegroundColor Red
    exit 1
}

$valid = @("high_performance", "balanced", "power_saver", "ultimate")

function Test-Scheme([string]$Name) {
    if ($valid -notcontains $Name) {
        Write-Host "ERROR: неизвестная схема '$Name'. Допустимо: $($valid -join ', ')" -ForegroundColor Red
        exit 1
    }
}

$toSet = @{}
if ($Game -ne "")   { Test-Scheme $Game;   $toSet["game_scheme"]   = $Game }
if ($Office -ne "") { Test-Scheme $Office; $toSet["office_scheme"] = $Office }
if ($Idle -ne "")   { Test-Scheme $Idle;   $toSet["idle_scheme"]   = $Idle }
if ($toSet.Count -eq 0) {
    Write-Host "ERROR: задайте хотя бы -Game, -Office или -Idle" -ForegroundColor Red
    exit 1
}

$lines = [System.IO.File]::ReadAllLines($Config)
$out = New-Object System.Collections.Generic.List[string]
$inPower = $false
$handled = @{}

foreach ($line in $lines) {
    if ($line -match '^power\s*:') { $inPower = $true }
    elseif ($inPower -and ($line -match '^\S')) { $inPower = $false }

    $matchedKey = $null
    foreach ($key in $toSet.Keys) {
        if ($inPower -and ($line -match ('^\s*' + [regex]::Escape($key) + '\s*:'))) {
            $matchedKey = $key
            break
        }
    }

    if ($matchedKey) {
        $indent = ($line -replace '^(\s*).*', '$1')
        $out.Add("$indent$matchedKey`: `"$($toSet[$matchedKey])`"")
        $handled[$matchedKey] = $true
    } else {
        $out.Add($line)
    }
}

# Вставка отсутствующих ключей сразу после строки "power:"
$missing = @($toSet.Keys | Where-Object { -not $handled.ContainsKey($_) })
if ($missing.Count -gt 0) {
    $out2 = New-Object System.Collections.Generic.List[string]
    foreach ($l in $out) {
        $out2.Add($l)
        if ($l -match '^power\s*:') {
            foreach ($k in $missing) {
                $out2.Add("  $k`: `"$($toSet[$k])`"")
            }
        }
    }
    $out = $out2
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($Config, $out, $utf8NoBom)

$parts = @()
foreach ($k in $toSet.Keys) { $parts += "$k=$($toSet[$k])" }
Write-Host "Схемы обновлены: $($parts -join ', ')" -ForegroundColor Green
exit 0

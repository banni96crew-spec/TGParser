# Register Telegram Lead Discovery Task Scheduler jobs (INF-009 / INF-011 / INF-017).
# Run once per operator Windows profile (no elevation required for current-user tasks).
#
# Prerequisites:
#   - uv installed and on PATH
#   - Repo checked out; set $RepoRoot below or pass -RepoRoot
#   - Optional secrets via User environment variables (TG_API_ID, TG_API_HASH, ...)
#
# Idempotent: unregisters existing tasks with the same names before creating.

[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,

    [Parameter()]
    [string]$PythonEntry = "uv run tld",

    [Parameter()]
    [string]$TaskPrefix = "TelegramLeadDiscovery"
)

$ErrorActionPreference = "Stop"

function Remove-TldTask([string]$Name) {
    $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }
}

function New-TldAction([string]$Arguments) {
    # Use cmd to keep PATH + uv resolution stable under Task Scheduler.
    $cmd = "cd /d `"$RepoRoot`" && $PythonEntry $Arguments"
    return New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $cmd"
}

Write-Host "RepoRoot=$RepoRoot"

# 1) Start at user logon — restart up to 3 times, 1 minute apart (INF-009)
$startName = "$TaskPrefix-Start"
Remove-TldTask $startName
$startAction = New-TldAction "start"
$startTrigger = New-ScheduledTaskTrigger -AtLogOn
$startSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)
Register-ScheduledTask `
    -TaskName $startName `
    -Action $startAction `
    -Trigger $startTrigger `
    -Settings $startSettings `
    -Description "Telegram Lead Discovery runtime (loopback UI + workers)" | Out-Null
Write-Host "Registered $startName"

# 2) Daily backup 03:00 Europe/Moscow ≈ 00:00 UTC (winter) / 00:00 UTC+3 local Moscow wall clock.
# Task Scheduler uses local machine time; document that host timezone should be Europe/Moscow.
$backupName = "$TaskPrefix-Backup"
Remove-TldTask $backupName
$backupAction = New-TldAction "backup"
$backupTrigger = New-ScheduledTaskTrigger -Daily -At "03:00"
Register-ScheduledTask `
    -TaskName $backupName `
    -Action $backupAction `
    -Trigger $backupTrigger `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable) `
    -Description "Daily online SQLite backup at 03:00 local (expect Europe/Moscow)" | Out-Null
Write-Host "Registered $backupName"

# 3) Daily purge 04:00 Europe/Moscow local wall clock
$purgeName = "$TaskPrefix-Purge"
Remove-TldTask $purgeName
$purgeAction = New-TldAction "purge"
$purgeTrigger = New-ScheduledTaskTrigger -Daily -At "04:00"
Register-ScheduledTask `
    -TaskName $purgeName `
    -Action $purgeAction `
    -Trigger $purgeTrigger `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable) `
    -Description "Daily retention purge at 04:00 local (expect Europe/Moscow)" | Out-Null
Write-Host "Registered $purgeName"

Write-Host "Done. Ensure host timezone is Europe/Moscow for INF schedule alignment."

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Fa-f0-9]{64}$')]
    [string]$ExpectedSha256,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmRestore,

    [string]$ProjectRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

if (-not $ConfirmRestore) {
    throw 'Operator confirmation is required; pass -ConfirmRestore explicitly.'
}

$resolvedRoot = [IO.Path]::GetFullPath($ProjectRoot)
$resolvedBackup = [IO.Path]::GetFullPath($BackupPath)
$target = Join-Path $resolvedRoot '.cursor\hooks.json'
$targetDirectory = Split-Path -Parent $target

if (-not (Test-Path -LiteralPath $resolvedBackup -PathType Leaf)) {
    throw "Known-good backup not found: $resolvedBackup"
}
if (-not (Test-Path -LiteralPath $targetDirectory -PathType Container)) {
    throw "Project hooks directory not found: $targetDirectory"
}

$actualHash = (Get-FileHash -LiteralPath $resolvedBackup -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $ExpectedSha256.ToLowerInvariant()) {
    throw "Backup checksum mismatch: expected $ExpectedSha256, observed $actualHash"
}

$backupText = [IO.File]::ReadAllText($resolvedBackup, [Text.UTF8Encoding]::new($false))
try {
    $parsed = $backupText | ConvertFrom-Json
} catch {
    throw "Known-good backup is not valid JSON: $($_.Exception.Message)"
}
if ($null -eq $parsed.version -or $null -eq $parsed.hooks) {
    throw 'Known-good backup lacks required version/hooks properties.'
}

$token = [Guid]::NewGuid().ToString('N')
$temporary = Join-Path $targetDirectory "hooks.restore.$token.tmp"
$rollback = Join-Path $targetDirectory "hooks.rollback.$token.json"

try {
    [IO.File]::WriteAllBytes($temporary, [IO.File]::ReadAllBytes($resolvedBackup))
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        [IO.File]::Replace($temporary, $target, $rollback, $true)
    } else {
        [IO.File]::Move($temporary, $target)
    }
    $restoredHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($restoredHash -ne $ExpectedSha256.ToLowerInvariant()) {
        if (Test-Path -LiteralPath $rollback -PathType Leaf) {
            [IO.File]::Replace($rollback, $target, $null, $true)
        }
        throw "Post-restore checksum mismatch: observed $restoredHash"
    }
    if (Test-Path -LiteralPath $rollback -PathType Leaf) {
        Remove-Item -LiteralPath $rollback -Force
    }
    Write-Output "Project hooks restored atomically: $target"
} finally {
    if (Test-Path -LiteralPath $temporary -PathType Leaf) {
        Remove-Item -LiteralPath $temporary -Force
    }
}

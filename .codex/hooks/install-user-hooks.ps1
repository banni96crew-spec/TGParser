# Copy project hooks to user ~/.cursor (PowerShell)
# REQUIRES SEPARATE EXPLICIT OPERATOR APPROVAL (AT-GOV-012).
# Project hooks are the sole enforcement owner. Do NOT run this script automatically.
# Run from repo root only after approval: powershell -File .cursor/hooks/install-user-hooks.ps1

param(
  [switch]$ConfirmApprovedInstall
)

if (-not $ConfirmApprovedInstall) {
  Write-Error "Refusing user-hooks install without -ConfirmApprovedInstall. Project hooks remain the sole enforcement owner."
  exit 2
}

$src = Join-Path $PSScriptRoot ".."
$dest = Join-Path $env:USERPROFILE ".cursor"

New-Item -ItemType Directory -Force -Path (Join-Path $dest "hooks\lib") | Out-Null
Copy-Item (Join-Path $src "hooks.json") (Join-Path $dest "hooks.json") -Force
Copy-Item (Join-Path $PSScriptRoot "*.mjs") (Join-Path $dest "hooks\") -Force
Copy-Item (Join-Path $PSScriptRoot "lib\*.mjs") (Join-Path $dest "hooks\lib\") -Force

$content = Get-Content (Join-Path $dest "hooks.json") -Raw
$content = $content -replace 'node \.cursor/hooks/', 'node hooks/'
Set-Content (Join-Path $dest "hooks.json") $content -NoNewline

Write-Host "User hooks installed to $dest"

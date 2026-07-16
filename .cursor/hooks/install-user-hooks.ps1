# Copy project hooks to user ~/.cursor (PowerShell)
# Run from repo root: powershell -File .cursor/hooks/install-user-hooks.ps1

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

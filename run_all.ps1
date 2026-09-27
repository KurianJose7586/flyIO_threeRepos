<#
.SYNOPSIS
  Starts all four FlyIO processes, each in its own window.

.DESCRIPTION
  Paths are relative to this script, so it runs the services in this
  repository wherever it is cloned. Run setup.ps1 once first.

    flyio-ai-llm            http://localhost:8000
    flyio-scraper-service   http://localhost:8080
    flyio-admin (API)       port from flyio-admin/.env (PORT, default 3000)
    flyio-admin (frontend)  http://localhost:5173   <- open this

.PARAMETER DryRun
  Print the command each window would run, without starting anything.
#>
[CmdletBinding()]
param([switch]$DryRun)

# Pure ASCII on purpose - see the note at the top of setup.ps1.
$Root = $PSScriptRoot

function Start-ServiceWindow([string]$Title, [string]$Dir, [string]$Command) {
    # Single quotes inside a single-quoted PowerShell string are doubled, so a
    # path such as "C:\Users\O'Brien\..." survives.
    $quotedDir = $Dir.Replace("'", "''")
    $full = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location -LiteralPath '$quotedDir'; $Command"
    if ($DryRun) {
        Write-Host "[$Title]"
        Write-Host "  $full"
        return
    }
    Write-Host "Starting $Title..."
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $full
}

$venvSetup = "if (!(Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\activate; pip install -r requirements.txt"

Start-ServiceWindow "flyio-ai-llm" (Join-Path $Root "flyio-ai-llm") `
    "$venvSetup; uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

Start-ServiceWindow "flyio-scraper-service" (Join-Path $Root "flyio-scraper-service") `
    "$venvSetup; uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload"

Start-ServiceWindow "flyio-admin" (Join-Path $Root "flyio-admin") `
    "npm install; npm run dev"

Start-ServiceWindow "flyio-admin frontend" (Join-Path (Join-Path $Root "flyio-admin") "frontend") `
    "npm install; npm run dev"

if (-not $DryRun) {
    Write-Host ""
    Write-Host "All services started in separate windows."
    Write-Host "Open http://localhost:5173 -> Knowledge Base -> By destination"
}

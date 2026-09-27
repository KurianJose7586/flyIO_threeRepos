<#
.SYNOPSIS
  Starts the FlyIO services and the admin's local database.

.DESCRIPTION
  Paths are relative to this script, so it runs the services in this
  repository wherever it is cloned. Run setup.ps1 once first.

    admin database          PostgreSQL from flyio-admin/.env (local only)
    flyio-ai-llm            http://localhost:8000
    flyio-scraper-service   http://localhost:8080
    flyio-admin (API)       port from flyio-admin/.env (PORT, default 3000)
    flyio-admin (frontend)  http://localhost:5173   <- open this

  By default each process gets its own window, opened a few seconds apart.
  With -OneWindow all four run in this window instead, output prefixed with
  the service name; Ctrl+C stops them all.

.PARAMETER OneWindow
  Run everything in the current window (via `concurrently`, installed with
  the admin's npm packages). Use this if separate windows fail to open.

.PARAMETER DryRun
  Print what would be started, without starting anything.
#>
[CmdletBinding()]
param(
    [switch]$OneWindow,
    [switch]$DryRun
)

# Pure ASCII on purpose - see the note at the top of setup.ps1.
$Root = $PSScriptRoot
$NotWindows = ($IsLinux -or $IsMacOS)   # $null on Windows PowerShell 5.1

if ($OneWindow) {
    # Each command runs through the platform shell from the repository root,
    # so relative folder names need no quoting even when the root path has
    # spaces. Services use their virtualenv's Python directly rather than an
    # activate script; dependencies are setup.ps1's job.
    if ($NotWindows) { $venvPy = ".venv/bin/python"; $frontend = "flyio-admin/frontend" }
    else { $venvPy = ".venv\Scripts\python.exe"; $frontend = "flyio-admin\frontend" }

    # The admin exits at startup if its database is not accepting
    # connections yet, so it waits for it (local-db.mjs --wait returns at
    # once when .env points at a remote database).
    $names = "db,llm,scraper,admin,web"
    $commands = @(
        "cd flyio-admin && node scripts/local-db.mjs",
        "cd flyio-ai-llm && $venvPy -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload",
        "cd flyio-scraper-service && $venvPy -m uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload",
        "cd flyio-admin && node scripts/local-db.mjs --wait && npm run dev",
        "cd $frontend && npm run dev"
    )
    $concurrently = Join-Path (Join-Path (Join-Path (Join-Path $Root "flyio-admin") "node_modules") "concurrently") (Join-Path "dist" (Join-Path "bin" "index.js"))

    if ($DryRun) {
        Write-Host "node $concurrently --names $names"
        foreach ($c in $commands) { Write-Host "  $c" }
        return
    }
    if (-not (Test-Path -LiteralPath $concurrently)) {
        throw "concurrently is not installed. Run setup.ps1 first (it installs the admin's npm packages)."
    }
    Write-Host "Starting all services in this window. Ctrl+C stops them all."
    Write-Host "Open http://localhost:5173 -> Knowledge Base -> By destination"
    Write-Host ""
    Push-Location -LiteralPath $Root
    try {
        & node $concurrently --names $names --prefix-colors "blue,magenta,cyan,green,yellow" @commands
    } finally {
        Pop-Location
    }
    return
}

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
    # On Windows 11 each new console is handed to Windows Terminal. Several
    # hand-offs at once can race, and one fails with
    # "[error 2147942632 (0x800700e8) when launching ...]" - "the pipe is
    # being closed". Spacing the launches out avoids it.
    Start-Sleep -Seconds 2
}

$venvSetup = "if (!(Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\activate; pip install -r requirements.txt"

Start-ServiceWindow "flyio-admin database" (Join-Path $Root "flyio-admin") `
    "node scripts/local-db.mjs"

Start-ServiceWindow "flyio-ai-llm" (Join-Path $Root "flyio-ai-llm") `
    "$venvSetup; uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

Start-ServiceWindow "flyio-scraper-service" (Join-Path $Root "flyio-scraper-service") `
    "$venvSetup; uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload"

Start-ServiceWindow "flyio-admin" (Join-Path $Root "flyio-admin") `
    "node scripts/local-db.mjs --wait; npm install; npm run dev"

Start-ServiceWindow "flyio-admin frontend" (Join-Path (Join-Path $Root "flyio-admin") "frontend") `
    "npm install; npm run dev"

if (-not $DryRun) {
    Write-Host ""
    Write-Host "All services started in separate windows (the database first)."
    Write-Host "If a window shows 'error 2147942632 (0x800700e8)', close them all and run:"
    Write-Host "    .\run_all.ps1 -OneWindow"
    Write-Host "Open http://localhost:5173 -> Knowledge Base -> By destination"
}

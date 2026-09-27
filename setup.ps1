<#
.SYNOPSIS
  One-time setup for the three FlyIO services on this machine.

.DESCRIPTION
  Safe to re-run: anything already in place is left alone.

    1. Checks for Python 3.11+ and Node/npm.
    2. Installs dependencies: a .venv per Python service, the headless
       browser the scraper crawls with, and npm packages for the admin.
    3. Creates each service's .env - copied from your existing setup with
       -CopyEnvFrom, otherwise from .env.example.
    4. Configures destination discovery: SEARCH_PROVIDER=wikimedia (free, no
       key), admin pointed at the local scraper, and the admin/scraper API
       keys made to match.
    5. Runs a live discovery check against Wikivoyage and Wikipedia.

  Any .env it changes is backed up first as .env.bak-<timestamp>.

.PARAMETER CopyEnvFrom
  Folder holding your existing service folders (flyio-admin, flyio-ai-llm,
  flyio-scraper-service), whose .env files should be reused. Only copies
  into services that have no .env yet.

.PARAMETER SkipInstall
  Skip dependency installation; only configure and check.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\setup.ps1 -CopyEnvFrom "C:\Users\Kurian Jose\Desktop\kurian stuff\FlyIO\Three repos"
#>
[CmdletBinding()]
param(
    [string]$CopyEnvFrom = "",
    [switch]$SkipInstall
)

# Written for Windows PowerShell 5.1 (what `powershell` runs) as well as 7+.
# Keep this file pure ASCII: 5.1 reads a BOM-less script as Windows-1252, where
# the bytes of an em dash end in a curly quote that 5.1 treats as a string
# delimiter - a script that runs fine elsewhere then fails to parse there.
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Admin = Join-Path $Root "flyio-admin"
$Scraper = Join-Path $Root "flyio-scraper-service"
$LlmSvc = Join-Path $Root "flyio-ai-llm"
$LocalScraperUrl = "http://localhost:8080"   # the port run_all.ps1 starts it on

$script:Changes = New-Object System.Collections.Generic.List[string]
$script:Warnings = New-Object System.Collections.Generic.List[string]
$script:BackedUp = @{}
$script:CreatedThisRun = @{}   # files this run created need no backup

function Write-Step([string]$Text) { Write-Host ""; Write-Host "== $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "   ok  $Text" -ForegroundColor Green }
function Add-Change([string]$Text) { $script:Changes.Add($Text); Write-Host "   set $Text" -ForegroundColor Yellow }
function Add-Warning([string]$Text) { $script:Warnings.Add($Text); Write-Host "   !!  $Text" -ForegroundColor Red }

# On Linux/macOS (pwsh 7) $IsWindows is $false; on Windows PowerShell 5.1 it
# does not exist at all, which is why this tests for "not Linux/macOS".
function Test-NotWindows { return ($IsLinux -or $IsMacOS) }

function Get-VenvPython([string]$ServiceDir) {
    if (Test-NotWindows) { return Join-Path $ServiceDir ".venv/bin/python" }
    return Join-Path $ServiceDir ".venv\Scripts\python.exe"
}

# Native commands are judged by their exit code only. Windows PowerShell 5.1
# turns a native command's redirected stderr into error records, and under the
# script-wide "Stop" the first one is fatal - so a tool merely printing a
# warning could end setup. Errors are therefore non-fatal inside the call.
function Invoke-Native([string]$What, [scriptblock]$Command) {
    $ErrorActionPreference = "Continue"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

# Version of a Python candidate such as @("py", "-3"), or $null when it is
# missing or unusable. Probing is expected to fail for some candidates: `py
# -3.11` with only 3.13 installed prints "No suitable Python runtime found",
# and the Microsoft Store `python` alias exits 9009. That stderr used to end
# the script on 5.1 before the next candidate was tried.
function Get-PythonVersion([string[]]$Candidate) {
    if (-not (Get-Command $Candidate[0] -ErrorAction SilentlyContinue)) { return $null }
    $ErrorActionPreference = "Continue"
    $pyArgs = @($Candidate | Select-Object -Skip 1)
    try {
        $out = & $Candidate[0] @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0) { return $null }
    $line = @($out | Where-Object { "$_" -match '^\d+\.\d+$' } | Select-Object -First 1)
    if ($line.Count -eq 0) { return $null }
    return [version]"$($line[0])"
}

# -- .env helpers ------------------------------------------------------------

function Read-EnvValue([string]$Path, [string]$Key) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        if ($line -match ('^\s*' + [regex]::Escape($Key) + '\s*=(.*)$')) {
            $value = $Matches[1].Trim()
            if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") { return $Matches[1] }
            return ($value -replace '\s+#.*$', '')
        }
    }
    return $null
}

function Backup-EnvOnce([string]$Path) {
    if ($script:BackedUp.ContainsKey($Path) -or $script:CreatedThisRun.ContainsKey($Path)) { return }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Copy-Item -LiteralPath $Path -Destination "$Path.bak-$stamp"
    $script:BackedUp[$Path] = $true
}

# Writes without a byte-order mark. Windows PowerShell 5.1's
# `Set-Content -Encoding UTF8` adds one, which python-dotenv then reads as
# part of the first variable's name - silently losing that setting.
function Set-EnvValue([string]$Path, [string]$Key, [string]$Value, [string]$Why) {
    if ((Read-EnvValue $Path $Key) -eq $Value) { return }
    Backup-EnvOnce $Path
    $lines = New-Object System.Collections.Generic.List[string]
    $found = $false
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        if (-not $found -and $line -match ('^\s*' + [regex]::Escape($Key) + '\s*=')) {
            $lines.Add("$Key=$Value"); $found = $true
        } else {
            $lines.Add($line)
        }
    }
    if (-not $found) { $lines.Add("$Key=$Value") }
    [System.IO.File]::WriteAllLines($Path, $lines.ToArray(), (New-Object System.Text.UTF8Encoding($false)))
    Add-Change "$Key in $(Split-Path -Leaf (Split-Path -Parent $Path))/.env - $Why"
}

function Test-Placeholder([string]$Value) {
    return ([string]::IsNullOrWhiteSpace($Value) -or $Value -match '^(change-me|your-|<)')
}

function Initialize-EnvFile([string]$ServiceDir, [string]$CopyFrom) {
    $name = Split-Path -Leaf $ServiceDir
    $envPath = Join-Path $ServiceDir ".env"
    if (Test-Path -LiteralPath $envPath) { Write-Ok "$name/.env exists"; return }

    if ($CopyFrom) {
        # Accept both layouts: <from>\<name>\.env and <from>\<name>\<name>\.env
        foreach ($candidate in @((Join-Path (Join-Path $CopyFrom $name) ".env"),
                                 (Join-Path (Join-Path (Join-Path $CopyFrom $name) $name) ".env"))) {
            if (Test-Path -LiteralPath $candidate) {
                Copy-Item -LiteralPath $candidate -Destination $envPath
                $script:CreatedThisRun[$envPath] = $true
                Add-Change "$name/.env copied from $candidate"
                return
            }
        }
        Add-Warning "${name}: no .env found under $CopyFrom - falling back to .env.example"
    }
    Copy-Item -LiteralPath (Join-Path $ServiceDir ".env.example") -Destination $envPath
    $script:CreatedThisRun[$envPath] = $true
    Add-Change "$name/.env created from .env.example"
}

# -- 1. Prerequisites --------------------------------------------------------

Write-Step "Checking prerequisites"

$Python = $null
# 3.11 first when present (the version the pinned requirements were verified
# on), then whatever newer Python is installed.
foreach ($candidate in @(@("py", "-3.11"), @("py", "-3"), @("python"), @("python3"))) {
    $version = Get-PythonVersion $candidate
    if ($version -and $version -ge [version]"3.11") {
        $Python = $candidate
        Write-Ok "Python $version ($($candidate -join ' '))"
        break
    }
}
if (-not $Python) { throw "Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm was not found. Install Node.js LTS from https://nodejs.org/." }
Write-Ok "npm $(& npm --version)"

# -- 2. Dependencies ---------------------------------------------------------

if ($SkipInstall) {
    Write-Step "Skipping dependency installation (-SkipInstall)"
} else {
    foreach ($svc in @($Scraper, $LlmSvc)) {
        $name = Split-Path -Leaf $svc
        Write-Step "Installing $name"
        $venvPy = Get-VenvPython $svc
        if (-not (Test-Path -LiteralPath $venvPy)) {
            $pyArgs = @($Python | Select-Object -Skip 1) + @("-m", "venv", (Join-Path $svc ".venv"))
            Invoke-Native "Creating $name virtualenv" { & $Python[0] @pyArgs }
            Add-Change "$name/.venv created"
        }
        Invoke-Native "pip install for $name" { & $venvPy -m pip install --disable-pip-version-check -q -r (Join-Path $svc "requirements.txt") }
        Write-Ok "Python packages installed"
    }

    Write-Step "Installing the scraper's headless browser"
    $scraperPy = Get-VenvPython $Scraper
    Invoke-Native "Playwright Chromium install" { & $scraperPy -m playwright install chromium }
    Write-Ok "Chromium ready"

    foreach ($dir in @($Admin, (Join-Path $Admin "frontend"))) {
        Write-Step "Installing npm packages in $(Split-Path -Leaf $dir)"
        Push-Location -LiteralPath $dir
        try { Invoke-Native "npm install in $dir" { & npm install --no-audit --no-fund } } finally { Pop-Location }
        Write-Ok "npm packages installed"
    }
}

# -- 3. Environment files ----------------------------------------------------

Write-Step "Environment files"
foreach ($svc in @($Admin, $Scraper, $LlmSvc)) { Initialize-EnvFile $svc $CopyEnvFrom }

$AdminEnv = Join-Path $Admin ".env"
$ScraperEnv = Join-Path $Scraper ".env"
$LlmEnv = Join-Path $LlmSvc ".env"

# -- 4. Discovery configuration ----------------------------------------------

Write-Step "Configuring destination discovery"

Set-EnvValue $ScraperEnv "SEARCH_PROVIDER" "wikimedia" "free Wikivoyage + Wikipedia search, no key"

# The admin must talk to the scraper started by run_all.ps1: a deployed
# scraper from before discovery existed has no /scrape/discover and every
# "Find sources" click would fail.
$scraperUrl = Read-EnvValue $AdminEnv "SCRAPER_SERVICE_URL"
if ($scraperUrl -notmatch '^https?://(localhost|127\.0\.0\.1):8080/?$') {
    Set-EnvValue $AdminEnv "SCRAPER_SERVICE_URL" $LocalScraperUrl "was '$scraperUrl'; discovery needs the local scraper"
} else {
    Write-Ok "admin uses the local scraper ($scraperUrl)"
}

# admin.SCRAPER_SERVICE_API_KEY must equal scraper.SERVICE_API_KEY, or every
# call is a 401. The admin's key wins; with none, a new one is generated.
$adminKey = Read-EnvValue $AdminEnv "SCRAPER_SERVICE_API_KEY"
if (Test-Placeholder $adminKey) {
    $adminKey = [guid]::NewGuid().ToString("N")
    Set-EnvValue $AdminEnv "SCRAPER_SERVICE_API_KEY" $adminKey "generated (was empty or a placeholder)"
}
if ((Read-EnvValue $ScraperEnv "SERVICE_API_KEY") -ne $adminKey) {
    Set-EnvValue $ScraperEnv "SERVICE_API_KEY" $adminKey "matched to admin's SCRAPER_SERVICE_API_KEY"
} else {
    Write-Ok "admin and scraper API keys match"
}

# The LLM service is reported, not changed: it may be a shared deployment,
# and discovery does not depend on it.
$llmUrl = Read-EnvValue $AdminEnv "LLM_SERVICE_URL"
if ($llmUrl -match '^https?://(localhost|127\.0\.0\.1)') {
    $adminLlmKey = Read-EnvValue $AdminEnv "LLM_SERVICE_API_KEY"
    $llmKey = Read-EnvValue $LlmEnv "SERVICE_API_KEY"
    # Parenthesised: a bare `Test-Placeholder $a -or ...` passes -or to the
    # function as an argument instead of evaluating it.
    if ((Test-Placeholder $adminLlmKey) -or ($adminLlmKey -ne $llmKey)) {
        Add-Warning "admin's LLM_SERVICE_API_KEY does not match flyio-ai-llm's SERVICE_API_KEY - storing embeddings will fail with 401 until they do"
    } else {
        Write-Ok "admin and local LLM service API keys match"
    }
} else {
    Write-Ok "admin uses the LLM service at $llmUrl (not checked)"
}

# The frontend dev server proxies /api to port 3000 (frontend/vite.config.ts),
# so any other admin PORT leaves every page failing to load data.
$adminPort = Read-EnvValue $AdminEnv "PORT"
if ($adminPort -and $adminPort -ne "3000") {
    Add-Warning "flyio-admin/.env: PORT is $adminPort, but the frontend dev server expects the admin on 3000"
}

foreach ($key in @("CMS_JWT_SECRET", "INITIAL_ADMIN_PASSWORD")) {
    if (Test-Placeholder (Read-EnvValue $AdminEnv $key)) { Add-Warning "flyio-admin/.env: $key is empty or a placeholder" }
}
if ((Test-Placeholder (Read-EnvValue $AdminEnv "DATABASE_URL")) -and (Test-Placeholder (Read-EnvValue $AdminEnv "PGHOST"))) {
    Add-Warning "flyio-admin/.env: set DATABASE_URL or PGHOST/PGUSER/PGPASSWORD/PGDATABASE - the admin will not start without a database"
}

# -- 5. Live discovery check -------------------------------------------------

Write-Step "Live check: searching Wikivoyage + Wikipedia for 'Jabalpur'"
$scraperPy = Get-VenvPython $Scraper
if (-not (Test-Path -LiteralPath $scraperPy)) {
    Add-Warning "scraper virtualenv missing - run without -SkipInstall first"
} else {
    Push-Location -LiteralPath $Scraper
    try {
        # Judged by exit code, like Invoke-Native.
        $ErrorActionPreference = "Continue"
        & $scraperPy (Join-Path "scripts" "try_discovery.py") "Jabalpur"
        $checkExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = "Stop"
        Pop-Location
    }
    if ($checkExit -eq 0) {
        Write-Ok "discovery returned real results"
    } else {
        Add-Warning "live discovery check failed (exit $checkExit) - check the internet connection, or a firewall/proxy blocking en.wikivoyage.org"
    }
}

# -- Summary -----------------------------------------------------------------

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
if ($script:Changes.Count -gt 0) {
    Write-Host "Changed:" -ForegroundColor Yellow
    foreach ($c in $script:Changes) { Write-Host "  - $c" }
    if ($script:BackedUp.Count -gt 0) { Write-Host "  (previous .env files kept as .env.bak-<timestamp>)" }
} else {
    Write-Host "Nothing needed changing." -ForegroundColor Green
}
if ($script:Warnings.Count -gt 0) {
    Write-Host "Needs attention:" -ForegroundColor Red
    foreach ($w in $script:Warnings) { Write-Host "  - $w" }
}
Write-Host ""
Write-Host "Next:  .\run_all.ps1   then open http://localhost:5173 -> Knowledge Base -> By destination"
Write-Host "================================================================" -ForegroundColor Cyan
if ($script:Warnings.Count -gt 0) { exit 1 }

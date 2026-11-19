$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envName = "sharppy-btv"
$dsDir = Join-Path $HOME ".sharppy\datasources"
New-Item -ItemType Directory -Force -Path $dsDir | Out-Null

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
  throw "Conda was not found. Install Miniforge/Miniconda, then reopen PowerShell."
}

$existing = conda env list | Select-String ("^" + [regex]::Escape($envName) + "\s")
if (-not $existing) {
  Write-Host "Creating native SHARPpy environment (first install may take several minutes)..."
  conda create -y -n $envName -c conda-forge python=3.10 "numpy<2" sharppy=1.4.0 pyside2 qtpy requests python-dateutil
  if ($LASTEXITCODE -ne 0) { throw "SHARPpy environment creation failed." }
} else {
  Write-Host "Reusing existing $envName environment."
}

Copy-Item (Join-Path $root "btv_cwa_latest.xml") (Join-Path $dsDir "btv_cwa_latest.xml") -Force
Copy-Item (Join-Path $root "btv_cwa.csv") (Join-Path $dsDir "btv_cwa.csv") -Force

$launcher = Join-Path $env:APPDATA "BTV-NSHARP"
New-Item -ItemType Directory -Force -Path $launcher | Out-Null
$launchPath = Join-Path $launcher "Launch-BTV-NSHARP.cmd"
@("@echo off", "call conda run -n $envName sharppy", "if errorlevel 1 pause") | Set-Content -Path $launchPath -Encoding ASCII

Write-Host ""
Write-Host "BTV NSHARP installed."
Write-Host "Start menu / desktop shortcut target: $launchPath"
Write-Host "Open SHARPpy > Data Sources and select BTV CWA RRFS (Latest), GFS, RAP, or HRRR."
Write-Host "These feeds use Penn State's latest BUFKIT cycles directly; no Worker hostname or API token is required."

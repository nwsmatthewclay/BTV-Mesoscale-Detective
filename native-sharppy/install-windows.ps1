$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envName = "sharppy-btv"
$dsDir = Join-Path $HOME ".sharppy\datasources"
New-Item -ItemType Directory -Force -Path $dsDir | Out-Null

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
  throw "Conda was not found. Install Miniforge/Miniconda first, then reopen PowerShell."
}
conda create -y -n $envName -c conda-forge python=3.10 sharppy=1.4.0 pyside2 requests python-dateutil
if ($LASTEXITCODE -ne 0) { throw "SHARPpy environment creation failed." }

$workerHost = Read-Host "Enter the Worker hostname (for example btv-sharppy-bufkit.your-subdomain.workers.dev)"
if ([string]::IsNullOrWhiteSpace($workerHost) -or $workerHost -match "[/ ]") { throw "Enter only the hostname, without https://" }
$xml = Get-Content (Join-Path $root "btv_cwa.xml") -Raw
$xml = $xml.Replace("BTV_WORKER_HOST", $workerHost.Trim())
Set-Content -Path (Join-Path $dsDir "btv_cwa.xml") -Value $xml -Encoding UTF8
Copy-Item (Join-Path $root "btv_cwa.csv") (Join-Path $dsDir "btv_cwa.csv") -Force

Write-Host ""
Write-Host "Native SHARPpy and BTV CWA data sources installed."
Write-Host "Launch with: conda run -n $envName sharppy"
Write-Host "Data Sources menu should include BTV CWA RRFS, GFS, RAP and HRRR."
Write-Host "Feeds use the versioned BTV BUFKIT archive through the Worker hostname you supplied."

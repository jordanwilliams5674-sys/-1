$ErrorActionPreference = "SilentlyContinue"

$root = "C:\premarket_mover_radar"
$python = "C:\Users\Dell\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$radarScript = Join-Path $root "scripts\radar_dashboard.py"
$siteScript = Join-Path $root "beidou_monitor_site\preview_server.py"
$url = "http://127.0.0.1:8786/dashboard"

$radarRunning = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -like "python*" -and
    $_.CommandLine -like "*premarket_mover_radar*radar_dashboard.py*" -and
    $_.CommandLine -like "*8766*"
  }

if (-not $radarRunning) {
  Start-Process -FilePath $python `
    -ArgumentList @($radarScript, "--host", "127.0.0.1", "--port", "8766", "--interval", "180", "--scan-now") `
    -WorkingDirectory $root `
    -WindowStyle Hidden
}

$siteRunning = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -like "python*" -and
    $_.CommandLine -like "*beidou_monitor_site*preview_server.py*"
  }

if (-not $siteRunning) {
  Start-Process -FilePath $python `
    -ArgumentList @($siteScript) `
    -WorkingDirectory (Join-Path $root "beidou_monitor_site") `
    -WindowStyle Hidden
}

for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Milliseconds 500
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8786/health" -TimeoutSec 2
    if ($response.StatusCode -eq 200) { break }
  } catch {}
}

Start-Process $url

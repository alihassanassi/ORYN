# START_WATCHMAN.ps1 – Start the JARVIS night watchman
# Register this with Windows Task Scheduler to run on login
$ROOT = "C:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab"
$PY   = "$ROOT\jarvis_env\Scripts\python.exe"
Set-Location $ROOT
Start-Process -FilePath $PY `
    -ArgumentList "-m", "runtime.night_watchman" `
    -WorkingDirectory $ROOT `
    -WindowStyle Hidden
Write-Host "JARVIS Night Watchman started." -ForegroundColor Green

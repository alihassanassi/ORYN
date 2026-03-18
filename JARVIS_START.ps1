param(
    [switch]$SkipPullCheck,
    [switch]$NoPrewarm
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

$PythonCandidates = @(
    "$Root\jarvis_env\Scripts\python.exe",
    "C:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab\jarvis_env\Scripts\python.exe",
    "C:\Users\aliin\AppData\Local\Programs\Python\Python311\python.exe"
)

$Python = $PythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

$OllamaCandidates = @(
    "C:\Users\aliin\AppData\Local\Programs\Ollama\ollama.exe",
    "ollama"
)

$OllamaExe = $OllamaCandidates | Where-Object {
    if ($_ -eq "ollama") { $true } else { Test-Path $_ }
} | Select-Object -First 1

$OllamaUrl = "http://localhost:11434"
$Models = @("qwen3:14b", "phi4-mini")
$LogFile = Join-Path $Root "jarvis_startup.log"

function Log {
    param([string]$msg)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

Set-Location $Root
"----" | Set-Content $LogFile
Log "JARVIS startup script begin"
Log "Root: $Root"

if (-not $Python) {
    Log "ERROR: Python not found in any expected location:"
    $PythonCandidates | ForEach-Object { Log "  $_" }
    exit 1
}
Log "Python: $Python"

# Performance tuning — set before Ollama starts
$env:OLLAMA_FLASH_ATTENTION   = "1"   # 20% speedup on RTX 40-series
$env:OLLAMA_NUM_PARALLEL      = "2"   # 2 concurrent requests
$env:OLLAMA_MAX_LOADED_MODELS = "2"   # keep qwen3:14b + phi4-mini hot
$env:OLLAMA_GPU_OVERHEAD      = "0"   # reclaim unused VRAM buffer
$env:OLLAMA_KEEP_ALIVE        = "-1"  # never unload

try {
    Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 3 -ErrorAction Stop | Out-Null
    Log "Ollama: already running"
}
catch {
    Log "Ollama: not running, starting..."
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5

    try {
        Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 5 -ErrorAction Stop | Out-Null
        Log "Ollama: started successfully"
    }
    catch {
        Log "ERROR: Ollama failed to start"
        exit 1
    }
}

if (-not $SkipPullCheck) {
    try {
        $pulledList = (Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -ErrorAction Stop).models.name
        foreach ($model in $Models) {
            $base = $model.Split(":")[0]
            $found = $pulledList | Where-Object { $_ -like "$base*" }
            if (-not $found) {
                Log "Model not found: $model ; pulling now"
                & $OllamaExe pull $model
                if ($LASTEXITCODE -ne 0) {
                    Log "ERROR: Failed to pull $model"
                    exit 1
                }
                Log "Model pulled: $model"
            }
            else {
                Log "Model ready: $model"
            }
        }
    }
    catch {
        Log "ERROR: Failed during model verification: $($_.Exception.Message)"
        exit 1
    }
}

if (-not $NoPrewarm) {
    Log "Starting background prewarm job"
    Start-Job -Name "jarvis_prewarm" -ScriptBlock {
        param($Url)

        try {
            $body1 = '{"model":"qwen3:14b","prompt":"init","stream":false,"keep_alive":"10m"}'
            Invoke-RestMethod -Method POST -Uri "$Url/api/generate" -Body $body1 -ContentType "application/json" -TimeoutSec 120 | Out-Null
        } catch {}

        try {
            $body2 = '{"model":"phi4-mini","prompt":"init","stream":false,"keep_alive":"10m"}'
            Invoke-RestMethod -Method POST -Uri "$Url/api/generate" -Body $body2 -ContentType "application/json" -TimeoutSec 60 | Out-Null
        } catch {}
    } -ArgumentList $OllamaUrl | Out-Null
}

Log "Launching JARVIS main.py"
Log "Primary LLM: qwen3:14b"
Log "Judge LLM: phi4-mini"
Log "TTS: Chatterbox"

& $Python "$Root\main.py"
$exitCode = $LASTEXITCODE

Log "main.py exited with code: $exitCode"

Get-Job -Name "jarvis_prewarm" -ErrorAction SilentlyContinue | Stop-Job -PassThru | Remove-Job -Force -ErrorAction SilentlyContinue

exit $exitCode

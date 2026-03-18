# JARVIS_GUARDIAN.ps1 — Auto-restart wrapper for JARVIS.
# Run this instead of main.py directly.
# JARVIS restarts automatically on crash (up to $MAX_RESTARTS times).
#
# To stop permanently:
#   - Press Ctrl+C in this window, OR
#   - Create STOP_GUARDIAN.flag in the jarvis_lab root directory
#
# Clean shutdown (user closes JARVIS window) stops the guardian automatically.
# Kill switch exit (code 42) stops the guardian automatically.

param(
    [int]$MaxRestarts   = 5,
    [int]$RestartDelay  = 8
)

$ROOT  = "C:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab"
$PY    = "$ROOT\jarvis_env\Scripts\python.exe"
$STOP  = "$ROOT\STOP_GUARDIAN.flag"
$LOGD  = "$ROOT\logs"
$LOG   = "$LOGD\guardian.log"

# Ensure logs directory exists
if (-not (Test-Path $LOGD)) { New-Item -ItemType Directory -Path $LOGD -Force | Out-Null }

function Write-Log {
    param([string]$Msg, [string]$Color = "Cyan")
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Msg"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $LOG -Value $line -Encoding UTF8
}

# Remove stale stop flag from a previous session
if (Test-Path $STOP) { Remove-Item $STOP -Force }

Write-Log "JARVIS Guardian v1.0 started" "Green"
Write-Log "Working directory: $ROOT" "Gray"
Write-Log "To stop: create STOP_GUARDIAN.flag or press Ctrl+C" "Yellow"
Write-Log ""

$restarts = 0

while ($true) {
    # Check for manual stop signal
    if (Test-Path $STOP) {
        Write-Log "STOP_GUARDIAN.flag detected — guardian stopping." "Yellow"
        break
    }

    $attempt = $restarts + 1
    Write-Log "Starting JARVIS (attempt $attempt of $($MaxRestarts + 1))..." "Cyan"

    try {
        $proc = Start-Process `
            -FilePath      $PY `
            -ArgumentList  "main.py" `
            -WorkingDirectory $ROOT `
            -PassThru `
            -NoNewWindow
        $proc.WaitForExit()
        $exitCode = $proc.ExitCode
    } catch {
        Write-Log "Failed to start JARVIS: $_" "Red"
        $exitCode = 1
    }

    Write-Log "JARVIS exited — code: $exitCode" "Gray"

    # Exit code meanings:
    #   0  = clean user shutdown (window closed normally)
    #   42 = kill switch activated (intentional emergency stop)
    #   1+ = crash
    if ($exitCode -eq 0) {
        Write-Log "Clean shutdown detected. Guardian stopping." "Green"
        break
    }
    if ($exitCode -eq 42) {
        Write-Log "Kill switch exit (code 42). Guardian stopping — not restarting." "Yellow"
        break
    }

    # Check stop flag again before deciding to restart
    if (Test-Path $STOP) {
        Write-Log "STOP_GUARDIAN.flag detected — not restarting." "Yellow"
        break
    }

    $restarts++
    if ($restarts -ge $MaxRestarts) {
        Write-Log "ERROR: JARVIS crashed $MaxRestarts times. Guardian giving up." "Red"
        Write-Log "Check $LOG for details." "Red"
        break
    }

    Write-Log "Restarting in $RestartDelay seconds... ($restarts/$MaxRestarts restarts used)" "Yellow"
    Start-Sleep -Seconds $RestartDelay
}

Write-Log "JARVIS Guardian terminated." "Gray"

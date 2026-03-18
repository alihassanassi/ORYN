# install_startup.ps1 — Install or repair JARVIS Windows login startup
# Run once from the jarvis_lab root:  .\install_startup.ps1
# Re-run whenever the project folder moves.
#
# What this does:
#   1. Removes ALL stale JARVIS entries from HKCU\SOFTWARE\...\Run
#   2. Removes ALL stale JARVIS VBS/LNK files from the Startup folder
#   3. Verifies JARVIS_Startup.vbs exists in the project root
#   4. Creates ONE shortcut (JARVIS.lnk) in the Startup folder → project-root VBS
#
# Result: single, clean startup entry. No duplicates. No popup errors.

$ErrorActionPreference = "Stop"

$Root       = Split-Path -Parent $MyInvocation.MyCommand.Path
$VbsPath    = Join-Path $Root "JARVIS_Startup.vbs"
$StartupDir = [System.Environment]::GetFolderPath("Startup")
$LnkPath    = Join-Path $StartupDir "JARVIS.lnk"

function Log {
    param($msg, [string]$color = "White")
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor $color
}

Log "=== JARVIS Startup Installer ===" Cyan
Log "Project root : $Root"
Log "Startup dir  : $StartupDir"
Log ""

# ── 1. Remove stale HKCU Run entries ─────────────────────────────────────────
$runKey   = "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
$runNames = @("JARVIS", "JARVIS_Startup", "JarvisAI", "jarvis")

foreach ($name in $runNames) {
    try {
        $val = (Get-ItemProperty -Path $runKey -Name $name -ErrorAction SilentlyContinue).$name
        if ($null -ne $val) {
            Remove-ItemProperty -Path $runKey -Name $name -Force
            Log "REMOVED registry Run entry : $name" Yellow
            Log "  was: $val" DarkYellow
        }
    } catch {
        # Property didn't exist — skip silently
    }
}

# ── 2. Remove stale VBS / LNK files from Startup folder ──────────────────────
$staleNames = @("JARVIS.vbs", "JARVIS_Startup.vbs", "jarvis.vbs",
                "JARVIS.lnk", "jarvis.lnk")

foreach ($f in $staleNames) {
    $target = Join-Path $StartupDir $f
    if (Test-Path $target) {
        Remove-Item $target -Force
        Log "REMOVED stale startup file  : $target" Yellow
    }
}

# ── 3. Verify JARVIS_Startup.vbs is present in project root ──────────────────
if (-not (Test-Path $VbsPath)) {
    Log ""
    Log "ERROR: JARVIS_Startup.vbs not found at:" Red
    Log "       $VbsPath" Red
    Log ""
    Log "Ensure you are running this script from the jarvis_lab directory," Red
    Log "and that JARVIS_Startup.vbs exists there." Red
    exit 1
}

Log "VBS launcher verified       : $VbsPath" Green

# ── 4. Create shortcut in Startup folder pointing to project-root VBS ────────
try {
    $wsh = New-Object -ComObject WScript.Shell
    $lnk = $wsh.CreateShortcut($LnkPath)
    $lnk.TargetPath      = $VbsPath
    $lnk.WorkingDirectory = $Root
    $lnk.Description     = "JARVIS AI - start at Windows login"
    $lnk.WindowStyle     = 7   # SW_SHOWMINNOACTIVE — suppresses any flash
    $lnk.Save()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh) | Out-Null
} catch {
    Log "ERROR creating shortcut: $_" Red
    exit 1
}

Log "CREATED startup shortcut    : $LnkPath" Green
Log "  -> $VbsPath" Green
Log ""
Log "=== Installation complete ===" Green
Log ""
Log "JARVIS will launch automatically at next Windows login." Cyan
Log "Ollama is started by JARVIS_START.ps1 if not already running."
Log ""
Log "To verify the startup entry:"
Log "  Get-ChildItem '$StartupDir'"
Log ""
Log "To test the launcher now (without rebooting):"
Log "  wscript.exe `"$VbsPath`""
Log ""
Log "To uninstall:"
Log "  Remove-Item `"$LnkPath`" -Force"
Log ""

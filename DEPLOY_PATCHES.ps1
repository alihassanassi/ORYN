# DEPLOY_PATCHES.ps1 — Run this once to deploy the 4 patch agents
# Open PowerShell in jarvis_lab\ and run: .\DEPLOY_PATCHES.ps1

$PY = ".\jarvis_env\Scripts\python.exe"
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== JARVIS PATCH DEPLOYMENT ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Install new dependencies
Write-Host "[1/3] Installing new dependencies (soundfile, scipy)..." -ForegroundColor Yellow
& $PY -m pip install soundfile scipy --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "      OK" -ForegroundColor Green
} else {
    Write-Host "      WARN: pip install had errors (non-fatal)" -ForegroundColor Yellow
}

# Step 2: Generate UI sounds
Write-Host "[2/3] Generating UI sounds..." -ForegroundColor Yellow
& $PY generate_sounds.py
if ($LASTEXITCODE -eq 0) {
    Write-Host "      OK — $(Get-ChildItem assets\sounds\*.wav | Measure-Object | Select-Object -ExpandProperty Count) WAV files in assets\sounds\" -ForegroundColor Green
} else {
    Write-Host "      WARN: sound generation failed (JARVIS will run silently)" -ForegroundColor Yellow
}

# Step 3: Quick syntax check
Write-Host "[3/3] Syntax check..." -ForegroundColor Yellow
$check = & $PY -c @"
import ast, pathlib
skip = {'__pycache__','.git','jarvis_env'}
bad = []
for f in pathlib.Path('.').rglob('*.py'):
    if any(s in str(f) for s in skip): continue
    try: ast.parse(f.read_text(encoding='utf-8', errors='replace'))
    except SyntaxError as e: bad.append(f'{f}:{e.lineno}: {e.msg}')
if bad:
    for b in bad: print('SYNTAX ERROR:', b)
    exit(1)
else:
    print('CLEAN')
"@
if ($LASTEXITCODE -eq 0) {
    Write-Host "      OK — $check" -ForegroundColor Green
} else {
    Write-Host "      ERRORS FOUND:" -ForegroundColor Red
    $check | ForEach-Object { Write-Host "      $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Fix syntax errors before launching." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== DEPLOYMENT COMPLETE ===" -ForegroundColor Green
Write-Host ""
Write-Host "Launch JARVIS with:" -ForegroundColor Cyan
Write-Host "  .\JARVIS_START.ps1" -ForegroundColor White
Write-Host "  — or —"
Write-Host "  .\jarvis_env\Scripts\python.exe main.py" -ForegroundColor White
Write-Host ""

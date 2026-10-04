param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$atharPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $atharPython)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $bootstrapPython = $pythonCommand.Source }
    else {
        $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $bundledPython) { $bootstrapPython = $bundledPython }
        else { throw 'Install Python 3.12 or later, then run start.ps1 again.' }
    }
    & $bootstrapPython -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    & $atharPython -m pip install -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Could not install requirements.' }
}
& $atharPython manage.py migrate
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }

$dbPath = Join-Path $PSScriptRoot 'db.sqlite3'
if (-not (Test-Path -LiteralPath $dbPath)) {
    Write-Host "Building initial database content..." -ForegroundColor Yellow
    & $atharPython manage.py seed_demo
    & $atharPython manage.py import_dorar_pilot --apply
    & $atharPython manage.py enrich_medina --apply
    & $atharPython manage.py enrich_stories --apply
    & $atharPython manage.py complete_journey --apply
}

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "              منصة أثَر | ATHAR PLATFORM                " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  رابط المنصة:     http://127.0.0.1:$Port/" -ForegroundColor Yellow
Write-Host "  لوحة الإدارة:    http://127.0.0.1:$Port/dashboard/" -ForegroundColor Yellow
Write-Host "  المستخدم:        admin" -ForegroundColor White
Write-Host "  كلمة المرور:     admin123456" -ForegroundColor White
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

& $atharPython manage.py runserver "127.0.0.1:$Port"


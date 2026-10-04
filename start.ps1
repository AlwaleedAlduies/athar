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
& $atharPython manage.py seed_demo
if ($LASTEXITCODE -ne 0) { throw 'Demo seeding failed.' }
Write-Host "ATHAR: http://127.0.0.1:$Port"
& $atharPython manage.py runserver "127.0.0.1:$Port"

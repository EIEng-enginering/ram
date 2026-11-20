# Development setup. Run from the project folder. Python 3.12 must be installed.
# The virtual environment lives outside OneDrive by default (short path, not synced):
#   %LOCALAPPDATA%\rammodel\venv   (override with the RAM_VENV environment variable)
$ErrorActionPreference = 'Stop'
$venv = if ($env:RAM_VENV) { $env:RAM_VENV } else { Join-Path $env:LOCALAPPDATA 'rammodel\venv' }
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
  & py -3.12 -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 virtual environment creation failed.' }
}
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install --upgrade pip
& $python -m pip install --editable $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'RAM Model installation failed.' }
Write-Host "RAM Model is installed (editable) in $venv. Run .\run.ps1 to start."

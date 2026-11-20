param([string] $Case)
$ErrorActionPreference = 'Stop'
$venv = if ($env:RAM_VENV) { $env:RAM_VENV } else { Join-Path $env:LOCALAPPDATA 'rammodel\venv' }
$python = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
  $legacy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
  if (Test-Path -LiteralPath $legacy -PathType Leaf) { $python = $legacy } else { throw 'Run setup.ps1 first.' }
}
$parameters = @('-m', 'rammodel.cli')
if ($Case) { $parameters += @('--case', $Case) }
& $python @parameters
exit $LASTEXITCODE

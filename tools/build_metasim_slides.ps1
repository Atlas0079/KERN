$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$miktexBin = Join-Path $env:LOCALAPPDATA "Programs\MiKTeX\miktex\bin\x64"

if (Test-Path $miktexBin) {
    $env:PATH = "$miktexBin;$env:PATH"
}

$xelatex = Get-Command xelatex -ErrorAction SilentlyContinue
if (-not $xelatex) {
    throw "xelatex not found. Install MiKTeX first, then rerun this script."
}

$outputDir = Join-Path $projectRoot "slides\outputs"
New-Item -ItemType Directory -Force $outputDir | Out-Null

Push-Location $projectRoot
try {
    xelatex -interaction=nonstopmode -halt-on-error -output-directory=slides\outputs slides\kern_meta_simulator.tex
    xelatex -interaction=nonstopmode -halt-on-error -output-directory=slides\outputs slides\kern_meta_simulator.tex
}
finally {
    Pop-Location
}

Write-Host "Built slides\outputs\kern_meta_simulator.pdf"

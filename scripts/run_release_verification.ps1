param(
    [switch]$IncludeMachineChecks,
    [switch]$NoDoctor
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== Model Lab Release Verification ===" -ForegroundColor Cyan
Write-Host "Root: $Root"

if (-not $NoDoctor) {
    Write-Host "[1/4] Running pipeline doctor / list-stages check..." -ForegroundColor Yellow
    python .\run_pipeline.py --list-stages
}

Write-Host "[2/4] Running Model Lab automated test suite..." -ForegroundColor Yellow
python -m pytest -q

Write-Host "[3/4] Compiling first-party Python..." -ForegroundColor Yellow
python -m compileall -q .\ui .\command_center .\pipeline .\run_pipeline.py .\run_command_center.py .\launch.py

if ($IncludeMachineChecks) {
    Write-Host "[4/4] Running target-machine checks..." -ForegroundColor Yellow
    python -m pytest -q .\tests\model_lab\test_machine_environment.py
} else {
    Write-Host "[4/4] Target-machine checks NOT RUN. Use -IncludeMachineChecks on the target Windows machine." -ForegroundColor Yellow
}

Write-Host "=== Verification complete ===" -ForegroundColor Green

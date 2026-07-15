# Run the full test suite (unit + docker integration).
# Unit tests only:            .\scripts\run_tests.ps1 -UnitOnly
param([switch]$UnitOnly)
$pytest = Join-Path $PSScriptRoot "..\.venv\Scripts\pytest.exe"
if ($UnitOnly) {
    & $pytest -m "not docker"
} else {
    & $pytest
}
exit $LASTEXITCODE

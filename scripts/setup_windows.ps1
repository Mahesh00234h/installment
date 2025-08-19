Param(
    [string]$PythonExe = "python",
    [string]$BackendDir = "..\backend"
)

$ErrorActionPreference = "Stop"

Write-Host "Setting up Tuition Escrow backend (Windows)" -ForegroundColor Cyan

Push-Location $PSScriptRoot

try {
    $backendPath = Resolve-Path $BackendDir
} catch {
    Write-Error "Backend directory not found: $BackendDir"
    exit 1
}

Set-Location $backendPath

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..."
    & $PythonExe -m venv .venv
}

Write-Host "Activating virtual environment..."
$venvActivate = Join-Path ".venv" "Scripts\Activate.ps1"
. $venvActivate

Write-Host "Installing requirements..."
pip install -r requirements.txt | Out-Host

Write-Host "Generating and funding a new Aptos Testnet account..."
& $PythonExe "tools\generate_account.py" | Out-Host

Write-Host "Done. Next steps:" -ForegroundColor Green
Write-Host "1) Publish the Move module with your new address (requires Aptos CLI):"
Write-Host "   - Edit move\\Move.toml and set TuitionEscrow to your address"
Write-Host "   - From the move folder:"
Write-Host "     aptos move publish --profile payer --named-addresses TuitionEscrow=0xYOUR_ADDR --included-artifacts none"
Write-Host "     aptos move run --profile payer --function \"0xYOUR_ADDR::tuition_escrow::init_module\""
Write-Host "2) Start the backend:"
Write-Host "     uvicorn app:app --reload --port 8000"
Write-Host "3) Open frontend\\index.html in your browser."

Pop-Location


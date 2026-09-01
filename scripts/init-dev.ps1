param(
    [switch]$Verify
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts/python.exe"
$BackendRequirements = Join-Path $Root "backend/requirements.txt"
$FrontendDir = Join-Path $Root "frontend"

function Assert-LastExitCode {
    param([string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found on PATH."
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found on PATH."
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Creating Python virtual environment: $VenvDir"
    & python -m venv $VenvDir
    Assert-LastExitCode "Create Python virtual environment"
}

Write-Host "Installing backend dependencies..."
& $VenvPython -m pip install --upgrade pip
Assert-LastExitCode "Upgrade pip"
& $VenvPython -m pip install -r $BackendRequirements
Assert-LastExitCode "Install backend dependencies"

Write-Host "Installing frontend dependencies..."
Push-Location $FrontendDir
try {
    $NpmVersion = (& npm --version).Trim()
    Assert-LastExitCode "Read npm version"
    $NpmMajor = [int]($NpmVersion.Split(".")[0])
    if ($NpmMajor -ge 12) {
        & npm install --allow-remote=all
    }
    else {
        & npm install
    }
    Assert-LastExitCode "Install frontend dependencies"
}
finally {
    Pop-Location
}

Write-Host "Generating frontend API types from FastAPI OpenAPI..."
Push-Location $Root
try {
    & $VenvPython scripts/export-openapi.py --output frontend/openapi.json
    Assert-LastExitCode "Export FastAPI OpenAPI"
    & npm --prefix frontend run generate:api
    Assert-LastExitCode "Generate frontend API types"
}
finally {
    Pop-Location
}

Write-Host "Checking backend runtime imports..."
Push-Location $Root
try {
    & $VenvPython -c "import faster_whisper; from backend.app.ffmpeg_tools import require_ffmpeg; print(f'Faster Whisper: {faster_whisper.__version__}'); print(f'FFmpeg: {require_ffmpeg()}')"
    Assert-LastExitCode "Check backend runtime imports"

    if ($Verify) {
        Write-Host "Running backend tests..."
        & $VenvPython -m pytest backend/tests
        Assert-LastExitCode "Run backend tests"

        Write-Host "Building frontend..."
        & npm --prefix frontend run build
        Assert-LastExitCode "Build frontend"
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Development environment is ready."
Write-Host "Backend: .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000"
Write-Host "Frontend: npm --prefix frontend run dev"

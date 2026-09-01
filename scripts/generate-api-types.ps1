[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project virtual environment is missing: $pythonPath"
}

& $pythonPath (Join-Path $PSScriptRoot "export-openapi.py") --output (Join-Path $repoRoot "frontend\openapi.json")
if ($LASTEXITCODE -ne 0) {
    throw "FastAPI OpenAPI export failed."
}

npm --prefix (Join-Path $repoRoot "frontend") run generate:api
if ($LASTEXITCODE -ne 0) {
    throw "TypeScript API type generation failed."
}

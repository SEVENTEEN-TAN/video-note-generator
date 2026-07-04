param(
    [switch]$BundleSmallModel
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    Write-Host "Installing frontend dependencies..."
    npm --prefix frontend install

    Write-Host "Building frontend..."
    npm --prefix frontend run build

    Write-Host "Installing Python dependencies..."
    python -m pip install -r backend/requirements.txt
    python -m pip install -r desktop/requirements.txt

    Write-Host "Building Windows desktop app..."
    python -m PyInstaller --clean --noconfirm desktop/VideoNoteGenerator.spec

    if ($BundleSmallModel) {
        $ModelCacheSource = Join-Path $Root "backend/models/faster-whisper"
        $ModelTargetRoot = Join-Path $Root "dist/VideoNoteGenerator/backend/models/faster-whisper"
        $SmallModelRef = Join-Path $ModelCacheSource "models--Systran--faster-whisper-small/refs/main"
        if (Test-Path $SmallModelRef) {
            Write-Host "Copying bundled Faster Whisper small model..."
            $SmallSnapshotId = (Get-Content -Raw $SmallModelRef).Trim()
            $SmallSnapshotSource = Join-Path $ModelCacheSource "models--Systran--faster-whisper-small/snapshots/$SmallSnapshotId"
            $SmallModelTarget = Join-Path $ModelTargetRoot "small"
            if (Test-Path $ModelTargetRoot) {
                Remove-Item -LiteralPath $ModelTargetRoot -Recurse -Force
            }
            New-Item -ItemType Directory -Force $SmallModelTarget | Out-Null
            foreach ($ModelFile in @("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")) {
                Copy-Item -LiteralPath (Join-Path $SmallSnapshotSource $ModelFile) -Destination (Join-Path $SmallModelTarget $ModelFile) -Force
            }
        }
        else {
            Write-Host "Faster Whisper small model cache not found; skipping model bundle."
        }
    }
    else {
        Write-Host "Skipping bundled Faster Whisper model. Use -BundleSmallModel to include it."
    }

    $FinalExe = Join-Path $Root "dist/VideoNoteGenerator/VideoNoteGenerator.exe"
    $FinalInternalDir = Join-Path $Root "dist/VideoNoteGenerator/_internal"
    if (-not (Test-Path $FinalExe)) {
        throw "Desktop build did not produce expected executable: $FinalExe"
    }
    if (-not (Test-Path $FinalInternalDir)) {
        throw "Desktop build did not produce expected internal dependency directory: $FinalInternalDir"
    }
    $FinalPythonDll = Get-ChildItem -LiteralPath $FinalInternalDir -Filter "python*.dll"
    if (-not $FinalPythonDll) {
        throw "Desktop build did not produce a bundled Python DLL under: $FinalInternalDir"
    }

    $IntermediateExe = Join-Path $Root "build/VideoNoteGenerator/VideoNoteGenerator.exe"
    if (Test-Path $IntermediateExe) {
        Remove-Item -LiteralPath $IntermediateExe -Force
    }

    Write-Host ""
    Write-Host "Desktop app built at: $FinalExe"
    Write-Host "Run the app from dist/VideoNoteGenerator, not from the PyInstaller build work directory."
}
finally {
    Pop-Location
}

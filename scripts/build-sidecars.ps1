param(
    [string]$PythonCommand = "python",
    [string]$TargetTriple = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$engineDir = Join-Path $repoRoot "engine"
$binaryDir = Join-Path $repoRoot "src-tauri\binaries"

if (-not $TargetTriple) {
    $hostLine = & rustc -vV | Select-String '^host:' | Select-Object -First 1
    if (-not $hostLine) {
        throw "Could not determine the Rust host target. Pass -TargetTriple explicitly."
    }
    $TargetTriple = ($hostLine.Line -replace '^host:\s*', '').Trim()
}

$extension = if ($IsWindows -or $env:OS -eq "Windows_NT") { ".exe" } else { "" }

Push-Location $engineDir
try {
    & $PythonCommand -m PyInstaller --clean --noconfirm bridge-engine.spec
    if ($LASTEXITCODE -ne 0) { throw "bridge-engine PyInstaller build failed" }

    & $PythonCommand -m PyInstaller --clean --noconfirm bridge-usfm-checker.spec
    if ($LASTEXITCODE -ne 0) { throw "bridge-usfm-checker PyInstaller build failed" }

    New-Item -ItemType Directory -Force -Path $binaryDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $engineDir "dist\bridge-engine$extension") `
        -Destination (Join-Path $binaryDir "bridge-engine-$TargetTriple$extension") -Force
    Copy-Item -LiteralPath (Join-Path $engineDir "dist\bridge-usfm-checker$extension") `
        -Destination (Join-Path $binaryDir "bridge-usfm-checker-$TargetTriple$extension") -Force
}
finally {
    Pop-Location
}

Write-Host "Built and copied Bridge sidecars for $TargetTriple"

param(
    [string]$PythonCommand = "",
    [string]$TargetTriple = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$engineDir = Join-Path $repoRoot "engine"
$binaryDir = Join-Path $repoRoot "src-tauri\binaries"

if (-not $PythonCommand) {
    $venvPython = if ($IsWindows -or $env:OS -eq "Windows_NT") {
        Join-Path $engineDir ".venv\Scripts\python.exe"
    } else {
        Join-Path $engineDir ".venv/bin/python"
    }
    $PythonCommand = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
}

& $PythonCommand -c "import PyInstaller, regex, uroman, wildebeest"
if ($LASTEXITCODE -ne 0) {
    throw "The selected Python environment is missing a release dependency. Run 'pip install -c constraints-py312-windows.txt -e .[dev,wildebeest]' in engine/ or pass -PythonCommand explicitly."
}

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

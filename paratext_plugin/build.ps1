# Builds TranslationCoreAIBridgePlugin.cs into a Paratext plugin using the
# C# compiler bundled with the .NET Framework (no Visual Studio / modern .NET
# SDK / NuGet required - confirmed available at this path on the dev machine
# this was built on; csc.exe ships with every Windows install that has .NET
# Framework 4.x, which Paratext 9 itself already requires).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File build.ps1              # build only
#   powershell -ExecutionPolicy Bypass -File build.ps1 -Deploy      # build + copy into
#                                                                      Paratext's plugins folder
#
# -Deploy writes into "C:\Program Files\Paratext 9\plugins\...", a
# protected system directory - requires an elevated (Run as Administrator)
# PowerShell and Paratext must not be running while it copies (per Paratext's
# own plugin documentation). Never run -Deploy without understanding that.

param(
    [switch]$Deploy
)

$ErrorActionPreference = 'Stop'

$paratextDir = 'C:\Program Files\Paratext 9'
$csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$outDir = Join-Path $PSScriptRoot 'build'
$pluginName = 'TranslationCoreAIBridgePlugin'
$fullConnector = Join-Path $paratextDir 'plugins\translationCoreAIBridge\translationCoreAIBridge.ptxplg'

if ($Deploy -and (Test-Path -LiteralPath $fullConnector)) {
    throw "A translationCore AI Bridge connector is already installed at $fullConnector. Both plugins use the same named pipe, so deploying this navigation-only companion beside it would create a conflict. Keep the existing connector or move it out of Paratext's plugins directory first."
}

if (-not (Test-Path $csc)) {
    throw "csc.exe not found at $csc - this script expects the .NET Framework 4.x compiler bundled with Windows."
}
foreach ($dll in @('PluginInterfaces.dll', 'CorePluginInterfaces.dll')) {
    if (-not (Test-Path (Join-Path $paratextDir $dll))) {
        throw "$dll not found under $paratextDir - is Paratext 9 installed at this path?"
    }
}

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outDll = Join-Path $outDir "$pluginName.dll"

$references = @(
    (Join-Path $paratextDir 'PluginInterfaces.dll'),
    (Join-Path $paratextDir 'CorePluginInterfaces.dll'),
    'System.Web.Extensions.dll',
    'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\netstandard.dll'
) -join ','

& $csc /nologo /target:library /platform:anycpu /out:$outDll /reference:$references (Join-Path $PSScriptRoot "$pluginName.cs")
if ($LASTEXITCODE -ne 0) {
    throw "csc.exe build failed with exit code $LASTEXITCODE"
}
Write-Output "Built: $outDll"

if ($Deploy) {
    $pluginFolder = Join-Path $paratextDir "plugins\$pluginName"
    New-Item -ItemType Directory -Force -Path $pluginFolder | Out-Null
    $ptxplg = Join-Path $pluginFolder "$pluginName.ptxplg"
    Copy-Item $outDll $ptxplg -Force
    $pdb = Join-Path $outDir "$pluginName.pdb"
    if (Test-Path $pdb) {
        Copy-Item $pdb (Join-Path $pluginFolder "$pluginName.pdb") -Force
    }
    Write-Output "Deployed: $ptxplg"
    Write-Output "Paratext must be restarted (and must not have been running during this copy) for the plugin to load."
}

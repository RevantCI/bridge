# translationCore AI Bridge - Logos COM automation helper.
#
# Real blocker closed here (see docs/BUILD_LOG.md's Phase 7 section):
# tc_ai_bridge/logos_connector.py's LogosConnectorClient spawns exactly this
# script with `powershell -STA -File logos_bridge.ps1` and talks to it over
# its own stdin/stdout as one JSON object per line (see that file's
# _request()/_start() methods) - this script did not exist anywhere in the
# repo before this pass. The persistent PowerShell process owns the JSON-lines
# transport; logos_com.vbs performs the native IDispatch calls in a short-lived
# Windows Script Host process for each request.
#
# Protocol (matches logos_connector.py exactly):
#   stdin,  one line: {"action": "state"}
#           one line: {"action": "navigate", "reference": "<Logos-formatted ref>", "origin_id": "..."}
#           one line: {"action": "close"}
#   stdout, one line per response: {"ok": true/false, ...fields, "error": "..."}
#
# API facts below are sourced from Faithlife's Logos4ComApiDemo and the Logos COM
# API documentation, then verified against Logos 53.1 on Windows:
#   - COM type library: Logos4Lib, GUID {81490292-5570-4D02-A2AC-7B828DBD0A8A}
#     (from Logos4ComApiDemo.csproj's <COMReference>).
#   - `new LogosLauncher()` -> `.Application` gives the running LogosApplication
#     instance, or null if Logos isn't running (from MainForm.cs).
#   - LogosApplication.ApiVersion, .Activate(), .Exit(), .ExecuteUri(uri),
#     .CreateNavigationRequest(), .Navigate(request), .DataTypes.LoadReference(text),
#     .DataTypes.GetDataType(text) are all real, confirmed method/property names
#     (from ApplicationPane.cs, NavigatePane.cs, DataTypesPane.cs).
#   - PanelActivated/PanelChanged/PanelOpened/PanelClosed/Exiting are real events
#     on LogosApplication; a panel object has at least a .Title property via the
#     ILogosPanel interface (from MainForm.cs's RecordPanelEvent).
#
# The original draft used a guessed ProgID and ActivePanel property. The correct
# ProgID is LogosBibleSoftware.Launcher, and the API exposes GetActivePanel() plus
# LogosPanel.GetCurrentReferencesAndHeadwords(). Current Logos returns typed COM
# objects that PowerShell's .NET wrapper can reject with HRESULT 0x80131165 even
# while the type library is registered. logos_com.vbs deliberately uses native
# IDispatch instead; this was verified for state, inbound reference reading, and
# outbound navigation on Logos 53.1.
#
# No event-driven push updates are attempted: a plain script host without a
# WinForms/WPF message loop cannot reliably pump COM event callbacks, and
# tc_ai_bridge/navigation.py's NavigationBroker is already designed around
# polling connectors (see its echo/settling-window logic), so this being
# poll-only (Bridge calls "state" periodically) is a deliberate match to how
# the rest of Bridge's navigation sync already works, not a shortcut.

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Web.Extensions
$script:serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer

function Invoke-LogosComShim($action, $reference = '', $uri = '') {
    $shim = Join-Path $PSScriptRoot 'logos_com.vbs'
    $cscript = Join-Path $env:SystemRoot 'System32\cscript.exe'
    if (-not (Test-Path -LiteralPath $shim)) {
        return New-ErrorResponse "Native Logos COM shim is missing: $shim"
    }
    if (-not (Test-Path -LiteralPath $cscript)) {
        return New-ErrorResponse "Windows Script Host could not be found: $cscript"
    }
    $arguments = @('//NoLogo', $shim, [string]$action)
    if ($action -eq 'navigate') {
        $arguments += @([string]$reference, [string]$uri)
    }
    $lines = @(& $cscript @arguments)
    $exitCode = $LASTEXITCODE
    $response = @{}
    foreach ($line in $lines) {
        $separator = ([string]$line).IndexOf('=')
        if ($separator -lt 1) { continue }
        $key = ([string]$line).Substring(0, $separator)
        $value = ([string]$line).Substring($separator + 1)
        $response[$key] = $value
    }
    foreach ($key in @('ok', 'detected', 'connected', 'navigation_ready')) {
        if ($response.ContainsKey($key)) { $response[$key] = $response[$key] -eq '1' }
    }
    if ($response.ContainsKey('api_version')) {
        try { $response.api_version = [int]$response.api_version } catch { $response.api_version = 0 }
    }
    if (-not $response.ContainsKey('ok')) {
        return New-ErrorResponse "Native Logos COM shim returned no response (exit code $exitCode)."
    }
    return $response
}

function New-OkResponse($extra) {
    $response = @{ ok = $true }
    foreach ($key in $extra.Keys) { $response[$key] = $extra[$key] }
    return $response
}

function New-ErrorResponse($message) {
    return @{ ok = $false; error = [string]$message }
}

function Handle-State {
    return Invoke-LogosComShim 'state'
}

function Handle-Navigate($payload) {
    $reference = [string]$payload.reference
    if ([string]::IsNullOrWhiteSpace($reference)) {
        return New-ErrorResponse "navigate requires a non-empty 'reference'."
    }
    $uri = [string]$payload.uri
    if ($uri -notmatch '^logosref:Bible\.[1-4]?[A-Za-z]+[0-9]+\.[0-9]+[A-Za-z]?$') {
        return New-ErrorResponse "navigate requires a valid Bridge-generated Logos Bible URI."
    }
    return Invoke-LogosComShim 'navigate' $reference $uri
}

# -- main loop: one JSON request per stdin line, one JSON response per stdout line --

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) {
        break
    }
    $line = $line.Trim()
    if ($line.Length -eq 0) {
        continue
    }
    $response = $null
    try {
        $request = $script:serializer.DeserializeObject($line)
        $action = [string]$request['action']
        switch ($action) {
            'state' { $response = Handle-State }
            'navigate' { $response = Handle-Navigate $request }
            'close' { $response = New-OkResponse @{} }
            default { $response = New-ErrorResponse "Unknown action: $action" }
        }
    }
    catch {
        $response = New-ErrorResponse $_.Exception.Message
    }
    if ($null -ne $response) {
        [Console]::Out.WriteLine($script:serializer.Serialize($response))
        [Console]::Out.Flush()
    }
    if ($action -eq 'close') {
        break
    }
}

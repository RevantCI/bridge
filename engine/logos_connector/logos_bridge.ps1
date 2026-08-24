# translationCore AI Bridge - Logos COM automation helper.
#
# Real blocker closed here (see docs/DEVELOPER_HANDOFF.md's Phase 7 section):
# tc_ai_bridge/logos_connector.py's LogosConnectorClient spawns exactly this
# script with `powershell -STA -File logos_bridge.ps1` and talks to it over
# its own stdin/stdout as one JSON object per line (see that file's
# _request()/_start() methods) - this script did not exist anywhere in the
# repo before this pass. -STA is required by the caller because classic COM
# interop (which this script uses to talk to Logos) needs a single-threaded
# apartment; do not remove PowerShell's -STA launch flag.
#
# Protocol (matches logos_connector.py exactly):
#   stdin,  one line: {"action": "state"}
#           one line: {"action": "navigate", "reference": "<Logos-formatted ref>", "origin_id": "..."}
#           one line: {"action": "close"}
#   stdout, one line per response: {"ok": true/false, ...fields, "error": "..."}
#
# WHAT IS AND ISN'T VERIFIED (read before debugging this against a real Logos install)
# ---------------------------------------------------------------------------------
# This session had no Logos installation available to test against (confirmed:
# not installed on this dev machine). Real, sourced facts below come from
# fetching LogosBible/Logos4ComApiDemo's actual .cs/.csproj source directly off
# GitHub (raw.githubusercontent.com), not from memory or the wiki docs alone -
# same "verify against real code" standard this project applies everywhere else,
# applied here as far as it could be without the real application:
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
# STILL GENUINELY UNVERIFIED - the two things most likely to need a real fix
# once Logos is actually installed and this is tested for the first time:
#   1. The ProgID string below ("Logos4Lib.LogosLauncher") is the standard
#      tlbimp <TypeLibraryName>.<CoClassName> convention, not something this
#      session ever saw registered in a real HKEY_CLASSES_ROOT. If New-Object
#      -ComObject fails, search the registry for the real ProgID (see the
#      Get-LogosLauncher function below for exactly how) and fix the constant.
#   2. The demo project never shows reading the CURRENTLY ACTIVE panel's Bible
#      reference (only pushing a new reference via Navigate() - a one-way
#      capability). Get-CurrentReference below is a best-effort guess
#      (tries $app.ActivePanel, then a couple of plausible property paths on
#      whatever panel object it finds) wrapped in try/catch so a wrong guess
#      degrades to an empty reference rather than crashing the helper. This is
#      the single most likely thing to need real correction once someone with
#      Logos installed can inspect the live COM object's actual members (e.g.
#      `$app | Get-Member` / `$app.ActivePanel | Get-Member` in an interactive
#      -STA PowerShell session).
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

$script:launcher = $null

function Get-LogosLauncher {
    if ($null -eq $script:launcher) {
        try {
            $script:launcher = New-Object -ComObject "Logos4Lib.LogosLauncher"
        }
        catch {
            $hits = @()
            try {
                $hits = Get-ChildItem 'HKCU:\Software\Classes' -ErrorAction SilentlyContinue |
                    Where-Object { $_.PSChildName -match 'Logos' } |
                    Select-Object -ExpandProperty PSChildName
            }
            catch { }
            $hint = if ($hits.Count -gt 0) { "Possible real ProgIDs found in the registry: $($hits -join ', ')" } else { 'No Logos-related ProgID found under HKCU:\Software\Classes - is Logos actually installed?' }
            throw "Could not create COM object 'Logos4Lib.LogosLauncher': $($_.Exception.Message). $hint"
        }
    }
    return $script:launcher
}

function Get-LogosApp {
    $launcher = Get-LogosLauncher
    return $launcher.Application
}

function Get-CurrentReferenceInfo($app) {
    # Best effort, deliberately defensive - see the file header's "STILL GENUINELY
    # UNVERIFIED" section. Every property access is individually guarded so a wrong
    # guess about one property name doesn't prevent the others from being tried.
    $result = @{ book_abbrev = ''; chapter = ''; verse = ''; reference_rendered = ''; panel_title = ''; panel_kind = '' }
    $panel = $null
    try { $panel = $app.ActivePanel } catch { }
    if ($null -eq $panel) {
        return $result
    }
    try { $result.panel_title = [string]$panel.Title } catch { }
    try { $result.panel_kind = $panel.GetType().Name } catch { }
    $dataType = $null
    try { $dataType = $panel.DataType } catch { }
    if ($null -eq $dataType) {
        return $result
    }
    try { $result.reference_rendered = [string]$dataType.ToString() } catch { }
    $details = $null
    try { $details = $dataType.Details } catch { }
    if ($null -ne $details) {
        try { $result.book_abbrev = [string]$details.Book } catch { }
        try { $result.chapter = [string]$details.Chapter } catch { }
        try { $result.verse = [string]$details.Verse } catch { }
    }
    return $result
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
    $app = $null
    try { $app = Get-LogosApp }
    catch { return (New-ErrorResponse $_.Exception.Message) }
    if ($null -eq $app) {
        return New-OkResponse @{ detected = $false; connected = $false; navigation_ready = $false; api_version = 0 }
    }
    $apiVersion = 0
    try { $apiVersion = [int]$app.ApiVersion } catch { }
    $refInfo = Get-CurrentReferenceInfo $app
    $fields = @{
        detected = $true
        connected = $true
        navigation_ready = $true
        api_version = $apiVersion
    }
    foreach ($key in $refInfo.Keys) { $fields[$key] = $refInfo[$key] }
    return New-OkResponse $fields
}

function Handle-Navigate($payload) {
    $reference = [string]$payload.reference
    if ([string]::IsNullOrWhiteSpace($reference)) {
        return New-ErrorResponse "navigate requires a non-empty 'reference'."
    }
    $app = $null
    try { $app = Get-LogosApp }
    catch { return (New-ErrorResponse $_.Exception.Message) }
    if ($null -eq $app) {
        return New-ErrorResponse "Logos is not running."
    }
    try {
        $dataTypeRef = $app.DataTypes.LoadReference($reference)
        $request = $app.CreateNavigationRequest()
        $request.Reference = $dataTypeRef
        $app.Navigate($request)
    }
    catch {
        return New-ErrorResponse "Logos navigation failed for '$reference': $($_.Exception.Message)"
    }
    $refInfo = Get-CurrentReferenceInfo $app
    $fields = @{ detected = $true; connected = $true; navigation_ready = $true }
    foreach ($key in $refInfo.Keys) { $fields[$key] = $refInfo[$key] }
    return New-OkResponse $fields
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

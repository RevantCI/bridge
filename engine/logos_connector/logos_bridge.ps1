# translationCore AI Bridge - Logos COM automation helper.
#
# Real blocker closed here (see docs/BUILD_LOG.md's Phase 7 section):
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
# The original unverified draft used the generated .NET interop namespace as a
# guessed ProgID and guessed at an ActivePanel property. Logos's documented
# PowerShell ProgID is LogosBibleSoftware.Launcher; its API exposes
# GetActivePanel() and LogosPanel.GetCurrentReferencesAndHeadwords(). Those
# documented late-bound COM calls are used below, so no generated interop
# assembly is required.
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
        $errors = @()
        foreach ($progId in @('LogosBibleSoftware.Launcher', 'LogosBibleSoftware.Launcher.1')) {
            try {
                $script:launcher = New-Object -ComObject $progId
                break
            }
            catch { $errors += "${progId}: $($_.Exception.Message)" }
        }
        if ($null -eq $script:launcher) {
            throw "Could not create the Logos COM launcher. $($errors -join ' | ') Logos may need to be repaired or registered."
        }
    }
    return $script:launcher
}

function Get-LogosApp {
    $launcher = Get-LogosLauncher
    return $launcher.Application
}

function Get-CurrentReferenceInfo($app) {
    # The API can return multiple references/headwords. Use the first Bible reference
    # exposed by the active panel and ignore headword-only entries.
    $result = @{ book_abbrev = ''; chapter = ''; verse = ''; reference_rendered = ''; panel_title = ''; panel_kind = '' }
    $panel = $null
    try { $panel = $app.GetActivePanel() } catch { }
    if ($null -eq $panel) {
        return $result
    }
    try { $result.panel_title = [string]$panel.Title } catch { }
    try { $result.panel_kind = [string]$panel.Kind } catch { }
    $references = $null
    try { $references = $panel.GetCurrentReferencesAndHeadwords() } catch { }
    if ($null -eq $references) { return $result }
    $count = 0
    try { $count = [int]$references.Count } catch { return $result }
    for ($index = 0; $index -lt $count; $index++) {
        $entry = $null
        $reference = $null
        $details = $null
        try { $entry = $references.Item($index) } catch { continue }
        try { $reference = $entry.Reference } catch { continue }
        if ($null -eq $reference) { continue }
        try { $details = $reference.Details } catch { continue }
        if ($null -eq $details) { continue }
        try { $result.book_abbrev = [string]$details.Book } catch { continue }
        try { $result.chapter = [string]$details.Chapter } catch { continue }
        try { $result.verse = [string]$details.Verse } catch { continue }
        try { $result.reference_rendered = [string]$reference.Render('display') } catch {
            try { $result.reference_rendered = [string]$reference.Render() } catch { }
        }
        if ($result.book_abbrev -and $result.chapter -and $result.verse) { break }
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

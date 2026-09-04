Option Explicit

' Native VBScript COM shim for Logos. Windows PowerShell wraps COM in .NET
' Runtime Callable Wrappers; current Logos builds can make that layer fail with
' "Typelib export: Type library is not registered" even though IDispatch works.
' cscript uses IDispatch directly, so keep all typed Logos object traversal here.

Dim action, referenceText, uriText
action = "state"
referenceText = ""
uriText = ""
If WScript.Arguments.Count > 0 Then action = LCase(Trim(WScript.Arguments(0)))
If WScript.Arguments.Count > 1 Then referenceText = Trim(WScript.Arguments(1))
If WScript.Arguments.Count > 2 Then uriText = Trim(WScript.Arguments(2))

Sub Emit(name, value)
    Dim text
    text = CStr(value)
    text = Replace(text, vbCr, " ")
    text = Replace(text, vbLf, " ")
    WScript.Echo name & "=" & text
End Sub

Sub Fail(message)
    Emit "ok", "0"
    Emit "error", message
    WScript.Quit 1
End Sub

Sub EmitState(app)
    Dim panel, references, entry, dataReference, details
    Dim index, count, bookAbbrev, chapter, verse, rendered, panelTitle, panelKind
    bookAbbrev = ""
    chapter = ""
    verse = ""
    rendered = ""
    panelTitle = ""
    panelKind = ""

    Err.Clear
    Set panel = app.GetActivePanel()
    If Err.Number = 0 And Not panel Is Nothing Then
        Err.Clear
        panelTitle = CStr(panel.Title)
        If Err.Number <> 0 Then panelTitle = ""
        Err.Clear
        panelKind = CStr(panel.Kind)
        If Err.Number <> 0 Then panelKind = ""

        Err.Clear
        Set references = panel.GetCurrentReferencesAndHeadwords()
        If Err.Number = 0 And Not references Is Nothing Then
            Err.Clear
            count = CInt(references.Count)
            If Err.Number <> 0 Then count = 0
            For index = 0 To count - 1
                Set entry = Nothing
                Set dataReference = Nothing
                Set details = Nothing
                Err.Clear
                Set entry = references.Item(index)
                If Err.Number = 0 And Not entry Is Nothing Then Set dataReference = entry.Reference
                If Err.Number = 0 And Not dataReference Is Nothing Then Set details = dataReference.Details
                If Err.Number = 0 And Not details Is Nothing Then
                    bookAbbrev = CStr(details.Book)
                    chapter = CStr(details.Chapter)
                    verse = CStr(details.Verse)
                    Err.Clear
                    rendered = CStr(dataReference.Render("display"))
                    If Err.Number <> 0 Then rendered = ""
                    If Len(bookAbbrev) > 0 And Len(chapter) > 0 And Len(verse) > 0 Then Exit For
                End If
            Next
        End If
    End If

    Emit "ok", "1"
    Emit "detected", "1"
    Emit "connected", "1"
    Emit "navigation_ready", "1"
    Emit "api_version", CStr(app.ApiVersion)
    Emit "book_abbrev", bookAbbrev
    Emit "chapter", chapter
    Emit "verse", verse
    Emit "reference_rendered", rendered
    Emit "panel_title", panelTitle
    Emit "panel_kind", panelKind
End Sub

On Error Resume Next
Dim launcher, app
Set launcher = CreateObject("LogosBibleSoftware.Launcher")
If Err.Number <> 0 Or launcher Is Nothing Then Fail "Could not create LogosBibleSoftware.Launcher: " & Err.Description

Err.Clear
Set app = launcher.Application
If Err.Number <> 0 Then Fail "Could not query the Logos application: " & Err.Description
If app Is Nothing Then
    Emit "ok", "1"
    Emit "detected", "0"
    Emit "connected", "0"
    Emit "navigation_ready", "0"
    Emit "api_version", "0"
    WScript.Quit 0
End If

If action = "state" Then
    EmitState app
    WScript.Quit 0
End If

If action <> "navigate" Then Fail "Unknown Logos helper action: " & action
If Len(referenceText) = 0 Then Fail "navigate requires a non-empty reference."
If Len(uriText) > 0 Then
    Err.Clear
    app.ExecuteUri uriText
    If Err.Number <> 0 Then Fail "Logos could not navigate to '" & referenceText & "': " & Err.Description
    EmitState app
    WScript.Quit 0
End If

Dim parsedReference, request
Err.Clear
Set parsedReference = app.DataTypes.LoadReference(referenceText)
If Err.Number <> 0 Or parsedReference Is Nothing Then Fail "Logos could not parse '" & referenceText & "': " & Err.Description

Err.Clear
Set request = app.CreateNavigationRequest()
If Err.Number <> 0 Or request Is Nothing Then Fail "Logos could not create a navigation request: " & Err.Description

Err.Clear
Set request.Reference = parsedReference
If Err.Number <> 0 Then Fail "Logos could not set the navigation reference: " & Err.Description

Err.Clear
app.Navigate request
If Err.Number <> 0 Then Fail "Logos could not navigate to '" & referenceText & "': " & Err.Description

EmitState app

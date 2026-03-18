' JARVIS_Startup.vbs — Windows login launcher for JARVIS
' Self-locating: resolves JARVIS_START.ps1 relative to this file's directory.
' This file lives in the jarvis_lab root.
' The Startup folder shortcut (JARVIS.lnk) points to THIS file — not a copy.
'
' If the project folder moves: re-run install_startup.ps1 to rebuild the shortcut.
' Do NOT move or copy this file outside the project root.

Option Explicit

Dim oShell, oFSO, scriptDir, ps1Path, cmd

Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

' Resolve the PS1 launcher relative to this VBS file's own location.
' This makes the launcher path-independent: works wherever the project lives.
scriptDir = oFSO.GetParentFolderName(WScript.ScriptFullName)
ps1Path   = scriptDir & "\JARVIS_START.ps1"

If Not oFSO.FileExists(ps1Path) Then
    oShell.Popup "JARVIS launcher not found:" & vbCrLf & _
                 ps1Path & vbCrLf & vbCrLf & _
                 "The project may have moved. Re-run install_startup.ps1 " & _
                 "from the jarvis_lab directory to repair.", _
                 0, "JARVIS Startup Error", 16
    WScript.Quit 1
End If

' Launch PowerShell hidden — no console window flash at login.
' -SkipPullCheck avoids the multi-minute model pull check at boot
' (models are already pulled; check can be done manually).
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden" & _
      " -File """ & ps1Path & """ -SkipPullCheck"

oShell.Run cmd, 0, False   ' 0 = hidden window, False = don't wait

Set oFSO   = Nothing
Set oShell = Nothing

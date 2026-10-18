Option Explicit
Dim shell, fs, folder, app
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
app = fs.BuildPath(folder, "SonarEdge.exe")
If Not fs.FileExists(app) Then
  MsgBox "Extract the complete Sonar Edge ZIP first.", 48, "Sonar Edge"
  WScript.Quit 1
End If
shell.CurrentDirectory = folder
shell.Run Chr(34) & app & Chr(34) & " --widget", 0, False

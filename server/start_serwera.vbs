Set fso = CreateObject("Scripting.FileSystemObject")
strScriptPath = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
' Uruchamia Pythona i serwer odbiorczy w tle, całkowicie ukrywając czarne okno konsoli (parametr 0)
WshShell.Run "pythonw """ & strScriptPath & "\server.py""", 0, False

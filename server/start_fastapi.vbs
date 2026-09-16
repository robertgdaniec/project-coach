Set fso = CreateObject("Scripting.FileSystemObject")
strScriptPath = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = strScriptPath
' Uruchamia serwer FastAPI (Uvicorn) w tle, ukrywajac czarne okno konsoli (parametr 0)
WshShell.Run "pythonw """ & strScriptPath & "\server_fastapi.py""", 0, False

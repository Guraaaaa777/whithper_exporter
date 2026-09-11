' 画面を出さずに常駐モードを起動する。
' スタートアップ（shell:startup）にショートカットを置くと、ログオン時に自動で立ち上がる。
Option Explicit
Dim shell, fso, root
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
shell.CurrentDirectory = root
' 0 = ウィンドウを表示しない, False = 終了を待たない
shell.Run "pythonw.exe -m withper_exporter daemon", 0, False

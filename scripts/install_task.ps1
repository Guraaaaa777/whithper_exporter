<#
.SYNOPSIS
    withper_exporter を Windows タスクスケジューラに登録し、バックグラウンドで定期実行します。

.DESCRIPTION
    ログオン時に開始し、以後 -IntervalMinutes ごとに `pythonw -m withper_exporter run` を
    実行します。pythonw を使うためコンソール画面は出ません。1回ごとに終了する方式なので、
    途中で失敗しても次回の実行で自動的に復帰します。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -IntervalMinutes 10

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -Config "C:\Users\me\AppData\Roaming\withper_exporter\config.toml"
#>
[CmdletBinding()]
param(
    [string]$TaskName = "WithperExporter",
    [int]$IntervalMinutes = 10,
    [string]$Python = "",
    [string]$Config = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if ($IntervalMinutes -lt 1) {
    throw "-IntervalMinutes は1以上を指定してください。"
}

# このスクリプトは <リポジトリ>\scripts\ に置かれている前提
$projectRoot = Split-Path -Parent $PSScriptRoot

if (-not $Python) {
    # コンソール画面を出さない pythonw を優先する
    $candidate = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $candidate) {
        $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
    }
    if (-not $candidate) {
        throw "Python が見つかりません。-Python でフルパスを指定してください。"
    }
    $Python = $candidate.Source
}
if (-not (Test-Path $Python)) {
    throw "Python が見つかりません: $Python"
}

$arguments = "-m withper_exporter run"
if ($Config) {
    if (-not (Test-Path $Config)) {
        Write-Warning "設定ファイルが見つかりません: $Config"
    }
    $arguments += " --config `"$Config`""
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and -not $Force) {
    throw "タスク '$TaskName' は既に存在します。置き換えるなら -Force を付けてください。"
}
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# -RepetitionDuration を省略すると「無期限に繰り返す」になる
$repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)).Repetition
$trigger.Repetition = $repetition

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -Hidden

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Whisper の文字起こし結果を定期的にテキストへ書き出します。" | Out-Null

Write-Host "登録しました: $TaskName"
Write-Host "  実行内容 : $Python $arguments"
Write-Host "  作業場所 : $projectRoot"
Write-Host "  実行間隔 : $IntervalMinutes 分ごと（ログオン時に開始）"
Write-Host ""
Write-Host "すぐ1回試すなら: Start-ScheduledTask -TaskName $TaskName"
Write-Host "状態を見るなら  : Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "解除するなら    : .\scripts\uninstall_task.ps1"

<#
.SYNOPSIS
    install_task.ps1 で登録したタスクを削除します。
#>
[CmdletBinding()]
param(
    [string]$TaskName = "WithperExporter"
)

$ErrorActionPreference = "Stop"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "タスク '$TaskName' は登録されていません。"
    return
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "削除しました: $TaskName"

# 安装「网关开机自启」计划任务（模仿微信监控那套：XiaoHua* 命名、登录触发）
$ErrorActionPreference = 'Stop'

$py     = 'pythonw.exe'
$script = '.\AI中转站\ai_relay.py'

$action = New-ScheduledTaskAction -Execute $py -Argument ('"' + $script + '"')

# 登录自启（和微信监控的 Boot 任务一个路数）
Register-ScheduledTask -TaskName 'XiaoHuaAIRelay' `
    -Action $action `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn) `
    -Force | Out-Null

Write-Host '装好了：计划任务 XiaoHuaAIRelay  ——  以后登录就自动起网关。'
Write-Host '查看：Get-ScheduledTask -TaskName XiaoHuaAIRelay'
Write-Host '删除：Unregister-ScheduledTask -TaskName XiaoHuaAIRelay -Confirm:$false'

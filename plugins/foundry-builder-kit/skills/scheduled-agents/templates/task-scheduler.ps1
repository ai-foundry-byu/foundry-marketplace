# Windows Task Scheduler. Run in PowerShell (as yourself, not admin) after editing the paths.
# Store the token as a user environment variable once (not in this file):
#   [Environment]::SetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "<token>", "User")
# OFF condition: Unregister-ScheduledTask -TaskName "daily-digest" -Confirm:$false

$Project = "$env:USERPROFILE\projects\your-app"
$Python  = (Get-Command python).Source          # or py.exe
$Claude  = (Get-Command claude).Source
$Kit     = "$env:USERPROFILE\bin"               # where you copied run_headless.py and deadman.py

$Action = New-ScheduledTaskAction -Execute $Python -WorkingDirectory $Project -Argument (
  "`"$Kit\run_headless.py`" --name daily-digest --prompt-file prompts\digest.md " +
  "--claude-bin `"$Claude`" --max-minutes 20 -- --max-turns 30")
$Trigger  = New-ScheduledTaskTrigger -Daily -At 7:15am
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "daily-digest" -Action $Action -Trigger $Trigger -Settings $Settings

# Deadman on its own task:
$Check = New-ScheduledTaskAction -Execute $Python -Argument (
  "`"$Kit\deadman.py`" check --name daily-digest --file `"$Project\.agent-jobs\daily-digest.heartbeat.json`" " +
  "--max-age 26h --webhook-file `"$env:USERPROFILE\.config\agent-alerts\webhook.url`"")
# webhook.url holds the URL on one line. With no working channel the check exits 3 and writes
# daily-digest.DEADMAN-ALERT.txt next to the heartbeat.
Register-ScheduledTask -TaskName "daily-digest-deadman" -Action $Check -Trigger (New-ScheduledTaskTrigger -Daily -At 10:00am)

# Test now:  Start-ScheduledTask -TaskName "daily-digest";  Get-ScheduledTaskInfo -TaskName "daily-digest"

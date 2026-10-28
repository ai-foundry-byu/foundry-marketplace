# Windows lane, PowerShell half: the agent's PowerShell lookup verbatim, the PowerShell
# screenshot snippet and the Get-WinEvent snippet. Results go to .qa\windows\pwsh-steps.tsv.
$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force .qa\windows | Out-Null
$log = ".qa\windows\pwsh-steps.tsv"
Set-Content $log ""
function Step($name, [scriptblock]$body) {
  Write-Host "::group::$name"
  $ok = $true
  try { & $body; if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { $ok = $false; Write-Host "exit $LASTEXITCODE" } } catch { $ok = $false; Write-Host "ERROR: $_" }
  Write-Host "::endgroup::"
  $v = if ($ok) { "PASS" } else { "FAIL" }
  Add-Content $log "$v`t$name"
  $global:LASTEXITCODE = 0
}

Write-Host "env:CLAUDE_PLUGIN_ROOT = $env:CLAUDE_PLUGIN_ROOT"

Step "agent s2 (PowerShell, verbatim): SKILL_DIR lookup + py -3 doctor.py" {
  $SKILL_DIR = "${CLAUDE_PLUGIN_ROOT}/skills/device-doctor"
  if (-not (Test-Path $SKILL_DIR)) { $SKILL_DIR = @(".claude/skills/device-doctor", "$env:CLAUDE_CONFIG_DIR/skills/device-doctor", "$HOME/.claude/skills/device-doctor") | Where-Object { Test-Path $_ } | Select-Object -First 1 }
  Write-Host "SKILL_DIR=[$SKILL_DIR]"
  if (-not $SKILL_DIR) { throw "SKILL_DIR is empty: `${CLAUDE_PLUGIN_ROOT} is a PowerShell variable, not the environment variable" }
  py -3 "$SKILL_DIR/scripts/doctor.py" --platform windows --out .qa
}

Step "[CORRECTED] PowerShell lookup with `$env:CLAUDE_PLUGIN_ROOT + py -3 doctor.py" {
  $SKILL_DIR = "$env:CLAUDE_PLUGIN_ROOT/skills/device-doctor"
  if (-not (Test-Path $SKILL_DIR)) { $SKILL_DIR = @(".claude/skills/device-doctor", "$env:CLAUDE_CONFIG_DIR/skills/device-doctor", "$HOME/.claude/skills/device-doctor") | Where-Object { Test-Path $_ } | Select-Object -First 1 }
  Write-Host "SKILL_DIR=[$SKILL_DIR]"
  py -3 "$SKILL_DIR/scripts/doctor.py" --platform windows --out .qa
}

Step "agent s5: PowerShell full-screen screenshot snippet (verbatim)" {
  Add-Type -AssemblyName System.Windows.Forms, System.Drawing
  $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
  [System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
  $bmp.Save(".qa\windows\S1-screen.png", [System.Drawing.Imaging.ImageFormat]::Png)
  if (-not (Test-Path .qa\windows\S1-screen.png)) { throw "no png" }
}

Step "agent s5: relative-path Save lands in the working directory" {
  $p = Resolve-Path .qa\windows\S1-screen.png -ErrorAction SilentlyContinue
  Write-Host "resolved: $p ; .NET CurrentDirectory: $([Environment]::CurrentDirectory)"
  if (-not $p) { throw "file not where the snippet says" }
}

Step "agent s6: Get-WinEvent snippet (verbatim)" {
  Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error','Application Hang','.NET Runtime'; StartTime=(Get-Date).AddMinutes(-30)} |
    Format-List TimeCreated, ProviderName, Message | Out-File .qa\windows\S1-events.txt
}

Step "agent s3: Get-StartApps lists AppUserModelIDs" { Get-StartApps | Select-Object -First 5 | Format-Table | Out-String | Write-Host }

Get-Content $log

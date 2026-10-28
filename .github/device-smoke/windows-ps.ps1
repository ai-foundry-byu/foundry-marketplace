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

Step "agent s2 PowerShell block with CLAUDE_PLUGIN_ROOT only as an ENV var (hook-style/copied snippet)" {
  $SKILL_DIR = "${CLAUDE_PLUGIN_ROOT}/skills/device-doctor"
  if (-not (Test-Path $SKILL_DIR)) { $SKILL_DIR = @(".claude/skills/device-doctor", "$env:CLAUDE_CONFIG_DIR/skills/device-doctor", "$HOME/.claude/skills/device-doctor") | Where-Object { Test-Path $_ } | Select-Object -First 1 }
  Write-Host "SKILL_DIR=[$SKILL_DIR]"
  if (-not $SKILL_DIR) { throw "SKILL_DIR is empty: `${CLAUDE_PLUGIN_ROOT} is a PowerShell variable, not the environment variable" }
  py -3 "$SKILL_DIR/scripts/doctor.py" --platform windows --out .qa
}

# Proposed replacement for the windows-qa.md PowerShell block (works as text-substituted plugin,
# as an env var, and standalone):
$fixed = @'
$SKILL_DIR = @("${CLAUDE_PLUGIN_ROOT}/skills/device-doctor", "$env:CLAUDE_PLUGIN_ROOT/skills/device-doctor", ".claude/skills/device-doctor", "$env:CLAUDE_CONFIG_DIR/skills/device-doctor", "$HOME/.claude/skills/device-doctor") | Where-Object { Test-Path $_ } | Select-Object -First 1
py -3 "$SKILL_DIR/scripts/doctor.py" --platform windows --out .qa
'@
Step "[CORRECTED] proposed block, env-var mode" {
  Invoke-Expression $fixed; Write-Host "SKILL_DIR=[$SKILL_DIR]"; if (-not $SKILL_DIR) { throw "empty" }
}

# The block above sets an environment variable. Claude Code instead substitutes ${CLAUDE_PLUGIN_ROOT}
# as TEXT in a plugin agent's body (seen in a headless session: the subagent's command held the literal path).
# So run the agent's PowerShell block extracted from agents/windows-qa.md in the two real modes.
$md = Get-Content -Raw "$env:GITHUB_WORKSPACE/plugins/foundry-devices/agents/windows-qa.md"
$block = [regex]::Match($md, '(?s)```powershell\r?\n(\$SKILL_DIR = .*?)```').Groups[1].Value
Write-Host "extracted block:`n$block"
$pluginRoot = "$env:GITHUB_WORKSPACE\plugins\foundry-devices"

Step "agent s2 PowerShell block, plugin mode (text-substituted root, env var unset)" {
  if (-not $block) { throw "block not found in windows-qa.md" }
  $saved = $env:CLAUDE_PLUGIN_ROOT; $env:CLAUDE_PLUGIN_ROOT = $null
  try { Invoke-Expression ($block.Replace('${CLAUDE_PLUGIN_ROOT}', $pluginRoot)) } finally { $env:CLAUDE_PLUGIN_ROOT = $saved }
  Write-Host "SKILL_DIR=[$SKILL_DIR] exit=$LASTEXITCODE"
  if (-not $SKILL_DIR) { throw "empty SKILL_DIR" }
}

Step "agent s2 PowerShell block, standalone mode (literal root, skill copied to .claude/skills)" {
  $saved = $env:CLAUDE_PLUGIN_ROOT; $env:CLAUDE_PLUGIN_ROOT = $null
  New-Item -ItemType Directory -Force .claude\skills | Out-Null
  Copy-Item -Recurse -Force "$pluginRoot\skills\device-doctor" .claude\skills\
  try { Invoke-Expression $block } finally { $env:CLAUDE_PLUGIN_ROOT = $saved; Remove-Item -Recurse -Force .claude }
  Write-Host "SKILL_DIR=[$SKILL_DIR] exit=$LASTEXITCODE"
  if ($SKILL_DIR -ne ".claude/skills/device-doctor") { throw "fallback did not resolve" }
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

Step "DEFECT CHECK agent s6: verbatim Get-WinEvent raises 'No events were found' when the log is clean" {
  $before = $Error.Count
  Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error','Application Hang','.NET Runtime'; StartTime=(Get-Date).AddMinutes(-30)} 2>$null | Out-Null
  Write-Host "new errors: $($Error.Count - $before) :: $($Error[0])"
}

Step "[CORRECTED] Get-WinEvent ... -ErrorAction SilentlyContinue writes an empty file, no error" {
  $before = $Error.Count
  Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error','Application Hang','.NET Runtime'; StartTime=(Get-Date).AddMinutes(-30)} -ErrorAction SilentlyContinue |
    Format-List TimeCreated, ProviderName, Message | Out-File .qa\windows\S1-events.txt
  if (-not (Test-Path .qa\windows\S1-events.txt)) { throw "no events file" }
  Write-Host "events file bytes: $((Get-Item .qa\windows\S1-events.txt).Length)"
}

Step "agent s3: Get-StartApps lists AppUserModelIDs" { Get-StartApps | Select-Object -First 5 | Format-Table | Out-String | Write-Host }

Get-Content $log

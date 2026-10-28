# Windows lane, PowerShell half: the agent's PowerShell lookup, screenshot and Get-WinEvent
# blocks, each extracted verbatim from agents/windows-qa.md. Results go to .qa\windows\pwsh-steps.tsv.
# Exits 1 if any step fails.
$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force .qa\windows | Out-Null
$log = ".qa\windows\pwsh-steps.tsv"
Set-Content $log ""
$global:fails = 0
function Step($name, [scriptblock]$body) {
  Write-Host "::group::$name"
  $ok = $true
  try { & $body; if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { $ok = $false; Write-Host "exit $LASTEXITCODE" } } catch { $ok = $false; Write-Host "ERROR: $_" }
  Write-Host "::endgroup::"
  $v = if ($ok) { "PASS" } else { "FAIL"; $global:fails++ }
  if (-not $ok) { Write-Host "::warning title=windows pwsh step failed::$name" }
  Add-Content $log "$v`t$name"
  $global:LASTEXITCODE = 0
}

Write-Host "env:CLAUDE_PLUGIN_ROOT = $env:CLAUDE_PLUGIN_ROOT"
$md = Get-Content -Raw "$env:GITHUB_WORKSPACE/plugins/foundry-devices/agents/windows-qa.md"
$block = [regex]::Match($md, '(?s)```powershell\r?\n(\$SKILL_DIR = .*?)```').Groups[1].Value
Write-Host "extracted lookup block:`n$block"
$pluginRoot = "$env:GITHUB_WORKSPACE\plugins\foundry-devices"

# FIXED D6: the block must work in all three ways it gets run.
Step "FIXED D6 agent s2 PowerShell block, env-var mode (CLAUDE_PLUGIN_ROOT only as an env var; block pasted as is)" {
  if (-not $block) { throw "block not found in windows-qa.md" }
  if (-not $env:CLAUDE_PLUGIN_ROOT) { throw "test setup: env var not set" }
  Remove-Item .qa\windows\doctor.json -ErrorAction SilentlyContinue
  Invoke-Expression $block
  Write-Host "SKILL_DIR=[$SKILL_DIR] exit=$LASTEXITCODE"
  if (-not $SKILL_DIR) { throw "empty SKILL_DIR in env-var mode" }
  if ((Resolve-Path $SKILL_DIR).Path -ne (Resolve-Path "$pluginRoot\skills\device-doctor").Path) { throw "resolved to the wrong skill dir" }
  if (-not (Test-Path .qa\windows\doctor.json)) { throw "doctor did not write .qa\windows\doctor.json" }
}

Step "FIXED D6 agent s2 PowerShell block, plugin mode (text-substituted root, env var unset)" {
  $saved = $env:CLAUDE_PLUGIN_ROOT; $env:CLAUDE_PLUGIN_ROOT = $null
  try { Invoke-Expression ($block.Replace('${CLAUDE_PLUGIN_ROOT}', $pluginRoot)) } finally { $env:CLAUDE_PLUGIN_ROOT = $saved }
  Write-Host "SKILL_DIR=[$SKILL_DIR] exit=$LASTEXITCODE"
  if (-not $SKILL_DIR) { throw "empty SKILL_DIR" }
}

Step "FIXED D6 agent s2 PowerShell block, standalone mode (no plugin root at all, skill copied to .claude/skills)" {
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

# FIXED D8: the section 6 event-log block, extracted verbatim. Runs it once as written, then once
# with the window moved into the future so the "no matching events" branch is taken for certain.
$evBlock = [regex]::Match($md, '(?s)```powershell\r?\n(\$ev = Get-WinEvent.*?)```').Groups[1].Value
Write-Host "extracted event-log block:`n$evBlock"
function Run-EvBlock($code) {
  Remove-Item .qa\windows\S1-events.txt -ErrorAction SilentlyContinue
  $out = & { Invoke-Expression $code } *>&1
  $errs = @($out | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] })
  $out | ForEach-Object { Write-Host "  > $_" }
  if ($errs.Count -gt 0) { throw "block wrote $($errs.Count) error(s): $($errs[0])" }
  if (-not (Test-Path .qa\windows\S1-events.txt)) { throw "no .qa\windows\S1-events.txt" }
  $body = (Get-Content -Raw .qa\windows\S1-events.txt)
  Write-Host "events file bytes: $((Get-Item .qa\windows\S1-events.txt).Length)"
  return $body
}

Step "FIXED D8 agent s6: Get-WinEvent block verbatim, no error output, writes S1-events.txt" {
  if (-not $evBlock) { throw "event-log block not found in windows-qa.md" }
  $body = Run-EvBlock $evBlock
  if (-not $body.Trim()) { throw "events file is empty" }
}

Step "FIXED D8 agent s6: clean log (window in the future) prints and writes 'no matching events', no error" {
  $clean = $evBlock.Replace('AddMinutes(-30)', 'AddMinutes(10)')
  if ($clean -eq $evBlock) { throw "could not move the window" }
  $body = Run-EvBlock $clean
  if ($body.Trim() -ne "no matching events") { throw "expected 'no matching events', got [$body]" }
}

Step "agent s3: Get-StartApps lists AppUserModelIDs" { Get-StartApps | Select-Object -First 5 | Format-Table | Out-String | Write-Host }

Get-Content $log
if ($global:fails -gt 0) { Write-Host "$($global:fails) PowerShell step(s) failed"; exit 1 }
exit 0

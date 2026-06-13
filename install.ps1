# Install Chinese Permission Popup skill for Claude Code
# Windows
param()

$ErrorActionPreference = "Stop"

$SkillName = "chinese-permission"
$SkillDir = "$env:USERPROFILE\.claude\skills\$SkillName"
$SettingsFile = "$env:USERPROFILE\.claude\settings.json"
$LocalSettings = "$env:USERPROFILE\.claude\settings.local.json"
$Timeout = 120

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Chinese Permission Popup Installer" -ForegroundColor Cyan
Write-Host "  Windows" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Check Python ──────────────────────────────────────────────
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
}

if (-not $pythonCmd) {
    Write-Host "✗ Python not found. Please install Python 3.6+ from https://python.org" -ForegroundColor Red
    exit 1
}

$pyVer = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "✓ Python $pyVer found ($pythonCmd)" -ForegroundColor Green

# ── Check PowerShell version ──────────────────────────────────
Write-Host "✓ PowerShell $($PSVersionTable.PSVersion) (built-in WinForms support)" -ForegroundColor Green

# ── Create skill directory ────────────────────────────────────
New-Item -ItemType Directory -Force -Path "$SkillDir\scripts\popups" | Out-Null
Write-Host "✓ Created $SkillDir" -ForegroundColor Green

# ── Copy files ────────────────────────────────────────────────
$srcDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item "$srcDir\SKILL.md" "$SkillDir\" -Force
Copy-Item "$srcDir\scripts\pretool_launcher.py" "$SkillDir\scripts\" -Force
Copy-Item "$srcDir\scripts\popups\dialog_win.ps1" "$SkillDir\scripts\popups\" -Force

# Ensure UTF-8 BOM for the PS1 file (critical for Chinese characters)
$ps1Path = "$SkillDir\scripts\popups\dialog_win.ps1"
$content = Get-Content $ps1Path -Raw -Encoding UTF8
$utf8Bom = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllText($ps1Path, $content, $utf8Bom)
Write-Host "✓ Files copied (UTF-8 BOM enforced)" -ForegroundColor Green

# ── Determine hook command ────────────────────────────────────
$hookCmd = "$pythonCmd `"$SkillDir\scripts\pretool_launcher.py`""
Write-Host "  Hook command: $hookCmd" -ForegroundColor DarkGray

# ── Configure settings.json ───────────────────────────────────
Write-Host ""
Write-Host "Configuring hooks..." -ForegroundColor Cyan

if (Test-Path $SettingsFile) {
    # Backup
    $backup = "$SettingsFile.bak.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Copy-Item $SettingsFile $backup
    Write-Host "✓ Backed up settings.json" -ForegroundColor Green

    # Merge using Python (same as Unix installer — cross-platform JSON logic)
    & $pythonCmd @"
import json

settings_path = r'$SettingsFile'
hook_cmd = r'$hookCmd'
timeout = $Timeout

with open(settings_path, 'r', encoding='utf-8') as f:
    settings = json.load(f)

hook_entry = {
    "matcher": "",
    "hooks": [
        {
            "type": "command",
            "command": hook_cmd,
            "timeout": timeout
        }
    ]
}

if "hooks" not in settings:
    settings["hooks"] = {}
if "PreToolUse" not in settings["hooks"]:
    settings["hooks"]["PreToolUse"] = []

existing = settings["hooks"]["PreToolUse"]
already = any(
    h.get("hooks", [{}])[0].get("command", "") == hook_cmd
    for h in existing
)

if not already:
    existing.append(hook_entry)
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    print('\033[0;32m✓\033[0m PreToolUse hook added to settings.json')
else:
    print('\033[0;36m⚠\033[0m PreToolUse hook already exists — skipped')
"@

} else {
    # Create fresh
    $json = @"
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$hookCmd",
            "timeout": $Timeout
          }
        ]
      }
    ]
  }
}
"@
    $json | Out-File $SettingsFile -Encoding UTF8
    Write-Host "✓ Created settings.json" -ForegroundColor Green
}

# ── Configure settings.local.json ─────────────────────────────
Write-Host ""
Write-Host "Configuring permission rules..." -ForegroundColor Cyan

$dangerousCmds = @(
    "Bash(rm *)",
    "Bash(rmdir *)",
    "Bash(del *)",
    "Bash(erase *)",
    "Bash(rd *)",
    "Bash(Remove-Item *)",
    "Bash(wipe *)",
    "Bash(shred *)",
    "Bash(srm *)",
    "Bash(Delete *)"
)

if (Test-Path $LocalSettings) {
    $backup = "$LocalSettings.bak.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Copy-Item $LocalSettings $backup
    Write-Host "✓ Backed up settings.local.json" -ForegroundColor Green

    # Merge using Python
    $cmdList = ($dangerousCmds | ForEach-Object { "r'''$_'''" }) -join ", "
    & $pythonCmd @"
import json

path = r'$LocalSettings'
cmds = [$cmdList]

with open(path, 'r', encoding='utf-8') as f:
    settings = json.load(f)

if "permissions" not in settings:
    settings["permissions"] = {}
if "allow" not in settings["permissions"]:
    settings["permissions"]["allow"] = []

allow_list = settings["permissions"]["allow"]
added = 0
for cmd in cmds:
    if cmd not in allow_list:
        allow_list.append(cmd)
        added += 1

with open(path, 'w', encoding='utf-8') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)

if added:
    print(f'\033[0;32m✓\033[0m {added} dangerous-command rules added to allow list')
else:
    print('\033[0;36m⚠\033[0m All rules already present — skipped')
"@

} else {
    # Create fresh
    $allowLines = ($dangerousCmds | ForEach-Object { "      `"$_`"" }) -join ",`n"
    $json = @"
{
  "permissions": {
    "allow": [
$allowLines
    ]
  }
}
"@
    $json | Out-File $LocalSettings -Encoding UTF8
    Write-Host "✓ Created settings.local.json" -ForegroundColor Green
}

# ── Done ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Skill dir : $SkillDir"
Write-Host "  Hook cmd  : $hookCmd"
Write-Host ""
Write-Host "  Restart Claude Code to activate."
Write-Host ""

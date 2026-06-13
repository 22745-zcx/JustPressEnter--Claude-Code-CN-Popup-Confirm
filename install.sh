#!/usr/bin/env bash
# Install Chinese Permission Popup skill for Claude Code
# macOS / Linux
set -euo pipefail

SKILL_NAME="chinese-permission"
SKILL_DIR="${HOME}/.claude/skills/${SKILL_NAME}"
SETTINGS_FILE="${HOME}/.claude/settings.json"
LOCAL_SETTINGS="${HOME}/.claude/settings.local.json"
HOOK_CMD="python3 ${SKILL_DIR}/scripts/pretool_launcher.py"
TIMEOUT=120

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Chinese Permission Popup Installer${NC}"
echo -e "${CYAN}  macOS / Linux${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# ── Check Python ──────────────────────────────────────────────
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo -e "${GREEN}✓${NC} Python ${PY_VER} found"
else
    echo -e "${RED}✗${NC} python3 not found. Please install Python 3.6+."
    exit 1
fi

# ── Check platform-specific dialog tools ───────────────────────
case "$(uname -s)" in
    Darwin)
        if command -v osascript &>/dev/null; then
            echo -e "${GREEN}✓${NC} osascript available (native macOS dialogs)"
        else
            echo -e "${RED}✗${NC} osascript not found (should be built-in on macOS)"
        fi
        ;;
    Linux)
        if command -v zenity &>/dev/null; then
            echo -e "${GREEN}✓${NC} zenity available (GTK dialogs)"
        elif command -v kdialog &>/dev/null; then
            echo -e "${GREEN}✓${NC} kdialog available (KDE dialogs)"
        else
            echo -e "${CYAN}⚠${NC} Neither zenity nor kdialog found — will use tkinter or terminal fallback"
            echo "  Install zenity for best experience: sudo apt install zenity"
        fi
        ;;
esac

# ── Create skill directory ────────────────────────────────────
mkdir -p "${SKILL_DIR}/scripts/popups"
echo -e "${GREEN}✓${NC} Created ${SKILL_DIR}"

# ── Copy files ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "${SCRIPT_DIR}/SKILL.md" "${SKILL_DIR}/"
cp "${SCRIPT_DIR}/scripts/pretool_launcher.py" "${SKILL_DIR}/scripts/"
cp "${SCRIPT_DIR}/scripts/popups/dialog_win.ps1" "${SKILL_DIR}/scripts/popups/"
chmod +x "${SKILL_DIR}/scripts/pretool_launcher.py"
echo -e "${GREEN}✓${NC} Files copied"

# ── Configure settings.json ───────────────────────────────────
echo ""
echo "Configuring hooks..."

if [ -f "${SETTINGS_FILE}" ]; then
    # Backup
    cp "${SETTINGS_FILE}" "${SETTINGS_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
    echo -e "${GREEN}✓${NC} Backed up settings.json"

    # Use Python to merge the hook config (handles JSON correctly)
    python3 << PYEOF
import json, sys

settings_path = "${SETTINGS_FILE}"
hook_cmd = "${HOOK_CMD}"
timeout = ${TIMEOUT}

with open(settings_path, 'r') as f:
    settings = json.load(f)

# Build the hook entry
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

# Ensure hooks.PreToolUse exists
if "hooks" not in settings:
    settings["hooks"] = {}
if "PreToolUse" not in settings["hooks"]:
    settings["hooks"]["PreToolUse"] = []

# Check if our hook is already registered
existing = settings["hooks"]["PreToolUse"]
already = any(
    h.get("hooks", [{}])[0].get("command", "") == hook_cmd
    for h in existing
)

if not already:
    existing.append(hook_entry)
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    print("\033[0;32m✓\033[0m PreToolUse hook added to settings.json")
else:
    print("\033[0;36m⚠\033[0m PreToolUse hook already exists — skipped")

PYEOF

else
    # Create fresh settings.json
    cat > "${SETTINGS_FILE}" << JSONEOF
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "${HOOK_CMD}",
            "timeout": ${TIMEOUT}
          }
        ]
      }
    ]
  }
}
JSONEOF
    echo -e "${GREEN}✓${NC} Created settings.json with PreToolUse hook"
fi

# ── Configure settings.local.json ─────────────────────────────
echo ""
echo "Configuring permission rules..."

DANGEROUS_CMDS=(
    "Bash(rm *)"
    "Bash(rmdir *)"
    "Bash(del *)"
    "Bash(erase *)"
    "Bash(rd *)"
    "Bash(Remove-Item *)"
    "Bash(wipe *)"
    "Bash(shred *)"
    "Bash(srm *)"
    "Bash(Delete *)"
)

if [ -f "${LOCAL_SETTINGS}" ]; then
    cp "${LOCAL_SETTINGS}" "${LOCAL_SETTINGS}.bak.$(date +%Y%m%d_%H%M%S)"
    echo -e "${GREEN}✓${NC} Backed up settings.local.json"

    # Build a Python list literal from the bash array
    PY_CMDS="["
    for cmd in "${DANGEROUS_CMDS[@]}"; do
        PY_CMDS+="\"$cmd\", "
    done
    PY_CMDS+="]"

    python3 -c "
import json

path = '${LOCAL_SETTINGS}'
cmds = ${PY_CMDS}

with open(path, 'r') as f:
    settings = json.load(f)

if 'permissions' not in settings:
    settings['permissions'] = {}
if 'allow' not in settings['permissions']:
    settings['permissions']['allow'] = []

allow_list = settings['permissions']['allow']
added = 0
for cmd in cmds:
    if cmd not in allow_list:
        allow_list.append(cmd)
        added += 1

with open(path, 'w') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)

if added:
    print(f'\033[0;32m✓\033[0m {added} dangerous-command rules added to allow list')
else:
    print('\033[0;36m⚠\033[0m All rules already present — skipped')
"

else
    # Create settings.local.json
    cat > "${LOCAL_SETTINGS}" << JSONEOF
{
  "permissions": {
    "allow": [
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
    ]
  }
}
JSONEOF
    echo -e "${GREEN}✓${NC} Created settings.local.json with allow rules"
fi

# ── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  Skill dir : ${SKILL_DIR}"
echo "  Hook cmd  : ${HOOK_CMD}"
echo ""
echo "  Restart Claude Code to activate."
echo ""

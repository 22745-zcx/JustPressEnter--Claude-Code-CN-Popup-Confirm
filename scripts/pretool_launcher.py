#!/usr/bin/env python3
"""
Cross-platform Chinese permission confirmation popup for Claude Code PreToolUse hook.

Reads tool call info from stdin (JSON), translates to natural Chinese description,
shows native OS confirmation dialog for dangerous operations.

Supported platforms:
  - Windows : PowerShell + WinForms (native look, no console flash)
  - macOS   : osascript AppleScript dialog (native, built-in)
  - Linux   : zenity → kdialog → tkinter → terminal fallback

IPC (Windows only): signal-file polling because WinForms runs in a separate process.
macOS & Linux dialogs block synchronously — simpler, no polling needed.

Author : cc (赵宸羲)
License: MIT
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Shared temp paths (Python & PowerShell both resolve $env:TEMP / $TMPDIR)
TEMP = tempfile.gettempdir()
SIGNAL_FILE = os.path.join(TEMP, "claude_pretool_signal.txt")
DESC_FILE = os.path.join(TEMP, "claude_pretool_desc.txt")

# Tools that NEVER need a popup
SAFE_TOOLS = frozenset({
    "Read", "Glob", "Grep", "Skill", "Agent", "WebFetch", "WebSearch",
})

# Bash commands whose first-word is harmless → auto-allow
SAFE_COMMANDS = frozenset({
    "echo", "ls", "cat", "head", "tail", "wc", "git", "grep", "find",
    "which", "type", "file", "node", "npm", "npx", "pnpm", "python",
    "python3", "pip", "pip3", "go", "cargo", "rustc", "make", "cmake",
    "gcc", "g++", "docker", "kubectl", "ps", "date", "cal", "uptime",
    "whoami", "id", "hostname", "pwd", "env", "printenv", "set", "unset",
    "export", "history", "sleep", "tar", "gzip", "gunzip", "zip", "unzip",
    "cd", "pushd", "popd", "diff", "sort", "uniq", "du", "df", "stat",
    "readlink", "realpath", "basename", "dirname", "tee", "seq", "xargs",
    "curl", "wget", "tasklist", "cp", "copy", "xcopy", "robocopy", "mkdir",
    "reg", "powershell", "chmod", "printf", "mv", "start",
})

HOOK_TIMEOUT_SEC = 120


# ═══════════════════════════════════════════════════════════════
# Platform helpers
# ═══════════════════════════════════════════════════════════════

def _platform() -> str:
    """Return 'windows' | 'macos' | 'linux'."""
    s = platform.system()
    if s == "Windows":
        return "windows"
    if s == "Darwin":
        return "macos"
    return "linux"


# ═══════════════════════════════════════════════════════════════
# Natural-language translation
# ═══════════════════════════════════════════════════════════════

def translate(tool_name: str, cmd: str, tool_input: dict | str | None) -> str:
    """Convert a tool invocation into a human-readable Chinese sentence."""

    if tool_name == "Bash" and cmd:
        trimmed = cmd.strip()
        parts = trimmed.split()
        prog = parts[0] if parts else ""
        rest = trimmed[len(prog):].strip() if len(parts) > 1 else ""

        # ── destructive commands ──────────────────────────
        if prog == "rm":
            flag_part = rest.split()[0] if rest else ""
            if flag_part in ("-rf", "-fr"):
                return f"强制递归删除：{rest}"
            if flag_part in ("-r", "-R"):
                return f"递归删除：{rest}"
            if flag_part == "-f":
                return f"强制删除：{rest}"
            return f"删除文件/目录：{rest}"

        if prog == "rmdir":
            return f"删除空目录：{rest}"

        if prog == "del":
            if rest and re.match(r"/[fF]", rest.split()[0]):
                return f"强制删除文件：{rest}"
            return f"删除文件：{rest}"

        if prog == "erase":
            return f"擦除文件：{rest}"

        if prog == "rd":
            return f"删除目录：{rest}"

        if prog == "Remove-Item":
            if rest and ("-Recurse" in rest or "-Force" in rest):
                return f"强制删除项目：{rest}"
            return f"删除项目：{rest}"

        if prog == "mv":
            return f"移动/重命名：{rest}"

        if prog in ("wipe",):
            return f"安全擦除：{rest}"
        if prog in ("shred",):
            return f"安全粉碎：{rest}"
        if prog in ("srm",):
            return f"安全删除：{rest}"
        if prog in ("Delete",):
            return f"删除操作：{rest}"

        return f"执行命令：{trimmed}"

    # ── Write ─────────────────────────────────────────────
    if tool_name == "Write":
        path = ""
        if isinstance(tool_input, str):
            path = tool_input
        elif isinstance(tool_input, dict):
            path = tool_input.get("file_path", "")
        return f"写入文件：{path}"

    # ── Edit ──────────────────────────────────────────────
    if tool_name == "Edit":
        path = ""
        old = ""
        if isinstance(tool_input, dict):
            path = tool_input.get("file_path", "")
            old_str = tool_input.get("old_string", "")
            if old_str:
                old = (old_str[:30] + "...") if len(old_str) > 30 else old_str
        info = f"{path} - 替换「{old}」" if old else path
        return f"编辑文件：{info}"

    return f"{tool_name} 操作"


# ═══════════════════════════════════════════════════════════════
# Dialog dispatchers (per platform)
# ═══════════════════════════════════════════════════════════════

# ── Windows · WinForms popup via PowerShell ────────────────────

def _dialog_windows(tool_name: str, desc: str) -> str:
    """Launch PowerShell WinForms popup; poll signal file for result."""
    # Write description file so the popup can read it
    with open(DESC_FILE, "w", encoding="utf-8") as fh:
        fh.write(f"{tool_name}|{desc}")

    # Clean stale signal
    _rm_f(SIGNAL_FILE)

    ps1 = os.path.join(SCRIPT_DIR, "popups", "dialog_win.ps1")

    subprocess.Popen(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", ps1,
            "-DescFile", DESC_FILE,
            "-SignalFile", SIGNAL_FILE,
        ],
        creationflags=0x08000000 if _platform() == "windows" else 0,  # CREATE_NO_WINDOW
    )

    # Poll (max HOOK_TIMEOUT_SEC)
    deadline = time.monotonic() + HOOK_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if os.path.exists(SIGNAL_FILE):
            result = _read_text(SIGNAL_FILE).strip().lower()
            _rm_f(SIGNAL_FILE)
            return result if result in ("allow", "deny") else "deny"
        time.sleep(0.5)

    return "deny"  # timeout


# ── macOS · native AppleScript dialog ──────────────────────────

def _dialog_macos(tool_name: str, desc: str) -> str:
    """Native osascript dialog — blocks until user clicks."""
    cn_map = {"Bash": "终端命令", "Write": "写入文件", "Edit": "编辑文件"}
    cn_name = cn_map.get(tool_name, tool_name)

    # AppleScript string escaping: backslash + double-quote
    safe_desc = desc.replace("\\", "\\\\").replace('"', '\\"')

    script = (
        'set theResult to button returned of (display dialog "羲羲 需要执行: '
        f'{cn_name}\\n\\n{safe_desc}\\n\\n'
        '允许执行此操作吗？" '
        'with title "Claude Code - 权限确认" '
        'buttons {"拒绝", "允许"} default button "允许" with icon caution)\n'
        'return theResult'
    )

    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=HOOK_TIMEOUT_SEC,
        )
        return "allow" if "允许" in proc.stdout else "deny"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "deny"


# ── Linux · zenity → kdialog → tkinter → terminal ─────────────

def _dialog_linux(tool_name: str, desc: str) -> str:
    """Try every available dialog backend; terminal prompt as last resort."""
    cn_map = {"Bash": "终端命令", "Write": "写入文件", "Edit": "编辑文件"}
    cn_name = cn_map.get(tool_name, tool_name)

    title = "Claude Code - 权限确认"
    text = f"羲羲 需要执行: {cn_name}\n\n{desc}\n\n允许执行此操作吗？"

    # 1) zenity (GNOME / GTK)
    if shutil.which("zenity"):
        try:
            rc = subprocess.run(
                ["zenity", "--question", f"--title={title}", f"--text={text}",
                 "--ok-label=允许", "--cancel-label=拒绝", "--width=500"],
                timeout=HOOK_TIMEOUT_SEC,
            ).returncode
            return "allow" if rc == 0 else "deny"
        except subprocess.TimeoutExpired:
            return "deny"

    # 2) kdialog (KDE)
    if shutil.which("kdialog"):
        try:
            rc = subprocess.run(
                ["kdialog", "--title", title, "--yesno", text,
                 "--yes-label", "允许", "--no-label", "拒绝"],
                timeout=HOOK_TIMEOUT_SEC,
            ).returncode
            return "allow" if rc == 0 else "deny"
        except subprocess.TimeoutExpired:
            return "deny"

    # 3) tkinter (bundled with Python on most distros)
    try:
        import tkinter.messagebox as mb
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        answer = mb.askyesno(title, text, parent=root)
        root.destroy()
        return "allow" if answer else "deny"
    except Exception:
        pass

    # 4) Terminal fallback
    print(f"\n{'='*55}", file=sys.stderr)
    print(f"  {title}", file=sys.stderr)
    print(f"  {text}", file=sys.stderr)
    print(f"{'='*55}", file=sys.stderr)
    try:
        ans = input("允许? (y/n): ").strip().lower()
        return "allow" if ans in ("y", "yes", "是", "允许") else "deny"
    except (EOFError, KeyboardInterrupt):
        return "deny"


# ── Unified entry ──────────────────────────────────────────────

def show_dialog(tool_name: str, desc: str) -> str:
    """Show the right native dialog for the current OS.  Returns 'allow' | 'deny'."""
    plat = _platform()
    if plat == "windows":
        return _dialog_windows(tool_name, desc)
    if plat == "macos":
        return _dialog_macos(tool_name, desc)
    return _dialog_linux(tool_name, desc)


# ═══════════════════════════════════════════════════════════════
# Hook output
# ═══════════════════════════════════════════════════════════════

def _emit(decision: str, reason: str = "") -> None:
    """Write the JSON decision to stdout (Claude Code consumes this)."""
    payload: dict = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
        }
    }
    if reason:
        payload["hookSpecificOutput"]["permissionDecisionReason"] = reason
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════
# Little utilities
# ═══════════════════════════════════════════════════════════════

def _rm_f(path: str) -> None:
    """Remove a file if it exists (best-effort)."""
    try:
        os.remove(path)
    except OSError:
        pass


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    # 1. Read stdin -------------------------------------------------
    try:
        raw = sys.stdin.readline()
    except Exception:
        _emit("defer", "stdin read error")
        return

    if not raw:
        _emit("defer", "empty stdin")
        return

    # 2. Parse JSON -------------------------------------------------
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _emit("defer", "json parse error")
        return

    tool_name: str = data.get("tool_name", "") or ""
    tool_input = data.get("tool_input", {})

    # 3. Extract Bash command ---------------------------------------
    cmd = ""
    if tool_input:
        if isinstance(tool_input, str):
            cmd = tool_input
        elif isinstance(tool_input, dict):
            cmd = tool_input.get("command", "") or ""

    # 4. Auto-allow: safe tools -------------------------------------
    if tool_name in SAFE_TOOLS or tool_name.startswith("Task"):
        _emit("allow", "safe tool")
        return

    # 5. Auto-allow: safe Bash commands -----------------------------
    if tool_name == "Bash" and cmd:
        first_word = (cmd.strip().split() or [""])[0]
        if first_word in SAFE_COMMANDS:
            _emit("allow", f"safe cmd: {first_word}")
            return

    # 6. Translate & confirm ----------------------------------------
    desc = translate(tool_name, cmd, tool_input)
    result = show_dialog(tool_name, desc)

    if result == "allow":
        _emit("allow", "user confirmed via popup")
    else:
        _emit("deny", "user denied via popup")


if __name__ == "__main__":
    main()

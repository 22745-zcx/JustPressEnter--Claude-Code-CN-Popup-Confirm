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

Author : 22745-zcx
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
# Operation impact analysis
# ═══════════════════════════════════════════════════════════════

# Source-code extensions
_SRC_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".swift", ".kt", ".rb", ".php",
    ".scala", ".clj", ".el", ".lua", ".r", ".m", ".mm",
})

# Configuration extensions
_CONF_EXTS = frozenset({
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".env", ".xml", ".properties", ".plist",
})

# Database extensions
_DB_EXTS = frozenset({
    ".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".sql",
})

# Log / temp / cache — disposable
_DISPOSABLE_EXTS = frozenset({
    ".log", ".tmp", ".temp", ".cache", ".pid", ".lock",
})

# Backup extensions
_BACKUP_EXTS = frozenset({".bak", ".backup", ".old", ".orig", ".swp", ".swo"})

# Version-control directories
_VCS_DIRS = frozenset({".git", ".svn", ".hg"})

# System paths (dangerous to touch)
_SYSTEM_PREFIXES = (
    "/etc/", "/usr/", "/boot/", "/lib/", "/lib64/",
    "/System/", "/Library/System/",
    "C:\\Windows\\", "C:\\Program Files\\", "C:\\Program Files (x86)\\",
)

# User-config paths
_USER_CONFIG_PREFIXES = (
    "~/.config/", "~/.local/", "~/Library/", "AppData/",
)

# Temp paths
_TEMP_PREFIXES = (
    "/tmp/", "/var/tmp/", "C:\\Users\\", "$TEMP\\", "$TMP\\", "$TMPDIR",
)


def _is_flag(token: str) -> bool:
    """Return True if *token* looks like a command-line flag, not a file path."""
    if token.startswith("--"):
        return True          # --force, --recursive
    if token.startswith("-") and len(token) > 1 and "/" not in token:
        return True          # -rf, -r, -f, -fr
    if re.match(r"^/[a-zA-Z]$", token):
        return True          # Windows: /f, /F, /q
    return False


def _strip_quotes(s: str) -> str:
    """Strip matching single/double quotes from a string."""
    s = s.strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    return s


def _path_in(path: str, prefixes: tuple[str, ...]) -> bool:
    """Check if *path* starts with any of *prefixes* (after normalisation)."""
    norm = path.replace("\\", "/").lower()
    for p in prefixes:
        if norm.startswith(p.replace("\\", "/").lower()):
            return True
    return False


def _extract_del_target(rest: str) -> tuple[str, str]:
    """From the argument tail of a delete command, return (display_path, flags).

    Handles: 'rm', 'rmdir', 'del', 'erase', 'rd', 'Remove-Item', 'wipe', 'shred', 'srm'
    """
    flags = ""
    tokens = rest.split()
    if not tokens:
        return "", ""
    # Consume leading flags (but NOT file-paths that start with /)
    idx = 0
    for tok in tokens:
        if _is_flag(tok):
            flags += tok + " "
            idx += 1
        else:
            break
    target = " ".join(tokens[idx:]) if idx < len(tokens) else ""
    target = _strip_quotes(target)
    return target, flags.strip()


def _classify_path(path: str) -> list[str]:
    """Return a list of classification tags for a path (most specific first)."""
    if not path:
        return []
    tags: list[str] = []
    lower = path.lower()
    name = os.path.basename(path)

    # Extension-based
    _, ext = os.path.splitext(name)
    ext_l = ext.lower()
    if ext_l in _DISPOSABLE_EXTS:
        tags.append("disposable")
    elif ext_l in _SRC_EXTS:
        tags.append("source")
    elif ext_l in _CONF_EXTS:
        tags.append("config")
    elif ext_l in _DB_EXTS:
        tags.append("database")
    elif ext_l in _BACKUP_EXTS:
        tags.append("backup")

    # Directory-based
    if any(d in lower.replace("\\", "/") for d in _VCS_DIRS):
        tags.append("vcs")
    if "node_modules" in lower.replace("\\", "/").split("/"):
        tags.append("node_modules")

    # Path-based
    if _path_in(path, _TEMP_PREFIXES):
        tags.append("temp")
    if _path_in(path, _SYSTEM_PREFIXES):
        tags.append("system")
    if _path_in(path, _USER_CONFIG_PREFIXES):
        tags.append("user_config")

    return tags


def explain(tool_name: str, cmd: str, tool_input: dict | str | None) -> str:
    """Generate a professional Chinese explanation of what this operation does.

    Returns a short paragraph suitable for display in the confirmation popup.
    """
    # ── Bash commands ────────────────────────────────────────
    if tool_name == "Bash" and cmd:
        trimmed = cmd.strip()
        parts = trimmed.split()
        prog = parts[0] if parts else ""
        rest = trimmed[len(prog):].strip() if len(parts) > 1 else ""

        # ── Deletion ───────────────────────────────────
        if prog in ("rm", "rmdir", "del", "erase", "rd",
                     "Remove-Item", "wipe", "shred", "srm", "Delete"):
            target, flags = _extract_del_target(rest)
            tags = _classify_path(target)

            # Build the explanation
            lines: list[str] = []

            # What is this file?
            if not target:
                return "无法解析操作对象，请手动确认此删除操作。"
            if not tags:
                lines.append("此路径由用户或脚本指定。")

            if "disposable" in tags:
                lines.append("这是一个日志/临时/缓存文件，删除后不影响程序运行，但可能丢失调试或恢复信息。")
            elif "source" in tags:
                lines.append("这是一个源代码文件。删除后将导致相关模块无法编译或运行，请确认是否为废弃代码。")
            elif "config" in tags:
                lines.append("这是一个配置文件。删除可能导致应用启动失败或行为异常，建议备份后再操作。")
            elif "database" in tags:
                lines.append("这是一个数据库文件。删除将永久丢失所有存储数据，且不可通过常规手段恢复。")
            elif "backup" in tags:
                lines.append("这是一个备份文件。删除将丢失该文件的唯一备份副本，请确认正式文件安全。")
            elif "vcs" in tags:
                lines.append("这是版本控制系统目录（如 .git/.svn）。删除将丢失全部提交历史、分支和标签。")
            elif "node_modules" in tags:
                lines.append("这是 npm 依赖目录，可通过 npm install 重新安装恢复，不影响项目源码。")
            elif "temp" in tags:
                lines.append("位于临时目录下，通常可安全删除，不影响系统运行。")
            elif "system" in tags:
                lines.append("⚠ 位于系统目录，删除可能导致系统无法启动或关键服务异常，建议谨慎操作。")
            elif "user_config" in tags:
                lines.append("位于用户配置目录，删除可能导致对应应用恢复默认设置或丢失个性化配置。")
            elif not tags:
                lines.append("删除后可通过备份或数据恢复软件尝试恢复。")

            # Recovery / severity
            if "node_modules" in tags:
                pass  # already covered
            elif "temp" in tags:
                pass  # already covered

            # Add flag implications
            if flags:
                flag_lower = flags.lower()
                if "-rf" in flag_lower or "-fr" in flag_lower:
                    lines.append("此操作为强制递归删除——将删除该目录及其所有子目录和文件，操作不可逆。")
                elif "-r" in flag_lower:
                    lines.append("此操作为递归删除——将删除该目录及其所有子目录和文件。")
                elif "-f" in flag_lower or "/f" in flag_lower:
                    lines.append("强制删除不会弹出二次确认，文件将直接移除。")

            return "\n".join(lines) if lines else "此路径由用户或脚本指定，请确认后操作。"

        # ── Move / Rename ──────────────────────────────
        if prog in ("mv", "move"):
            tokens = rest.split()
            if len(tokens) < 2:
                return "移动/重命名操作。请确认源路径和目标路径正确。"

            src = _strip_quotes(tokens[0])
            dst = _strip_quotes(" ".join(tokens[1:]))
            src_dir = os.path.dirname(src)
            dst_dir = os.path.dirname(dst)
            src_ext = os.path.splitext(src)[1]
            dst_ext = os.path.splitext(dst)[1]

            # Rename only (same directory)
            if src_dir == dst_dir and os.path.basename(src) != os.path.basename(dst):
                if src_ext != dst_ext and dst_ext:
                    return (f"在同一目录下重命名并修改扩展名（{src_ext} → {dst_ext}）。"
                            "修改扩展名可能导致关联程序无法打开该文件，请确认新扩展名正确。")
                return "在同一目录下重命名，仅修改文件名，文件内容和存储位置不变。"

            if src_dir == dst_dir:
                return "源和目标路径相同，不会产生任何效果。"

            # Cross-device detection (best-effort via heuristics)
            if "/tmp/" in dst or "$TEMP" in dst.upper() or dst.startswith("/var/tmp"):
                return "将文件移动到临时目录。临时目录中的文件可能在系统重启后被自动清理。"

            return "将文件移动到新位置。原路径的文件将被移除，内容转移到目标路径。操作时间取决于文件大小。"

        # ── Fallback ───────────────────────────────────
        return "此命令由用户或脚本指定，系统无法自动分析其影响范围。请确认该命令的安全性后操作。"

    # ── Write ─────────────────────────────────────────────────
    if tool_name == "Write":
        path = ""
        if isinstance(tool_input, str):
            path = tool_input
        elif isinstance(tool_input, dict):
            path = tool_input.get("file_path", "")
        path = _strip_quotes(path)
        tags = _classify_path(path)

        if not path:
            return "将内容写入文件。请确认目标路径正确。"

        if "source" in tags:
            return (f"将内容写入源代码文件「{path}」。"
                    "若文件已存在，原有代码将被覆盖且无法恢复。")
        if "config" in tags:
            return (f"将内容写入配置文件「{path}」。"
                    "错误的配置可能导致应用启动失败，建议先备份原文件。")
        if "temp" in tags:
            return (f"将内容写入临时文件「{path}」。"
                    "临时目录中的文件可能在系统重启后被清理。")

        return (f"将内容写入「{path}」。"
                "若文件已存在，原有内容将被覆盖；若不存在，则创建新文件。")

    # ── Edit ──────────────────────────────────────────────────
    if tool_name == "Edit":
        path = ""
        old_str = ""
        if isinstance(tool_input, dict):
            path = tool_input.get("file_path", "")
            old_str = tool_input.get("old_string", "")
        path = _strip_quotes(path)
        tags = _classify_path(path)

        base = ""
        if not path:
            base = "修改文件中的指定文本片段。请确认目标文件正确。"
        elif "source" in tags:
            base = (f"修改源代码文件「{path}」中的指定文本。"
                    "仅替换匹配到的片段，不会影响文件其他部分。")
        elif "config" in tags:
            base = (f"修改配置文件「{path}」中的指定文本。"
                    "配置变更将在下次读取该文件时生效，错误修改可能导致服务异常。")
        elif "system" in tags:
            base = (f"⚠ 编辑系统文件「{path}」。"
                    "错误修改可能导致系统或服务异常，建议先备份。")
        else:
            base = (f"修改文件「{path}」中的指定文本。"
                    "仅替换匹配到的第一个片段。")

        # Show what exactly is being changed
        if old_str:
            preview = old_str if len(old_str) <= 60 else old_str[:57] + "..."
            base += f"\n将替换文本：「{preview}」"

        return base

    return f"{tool_name} 操作——请确认此操作的安全性后继续。"


# ═══════════════════════════════════════════════════════════════
# Dialog dispatchers (per platform)
# ═══════════════════════════════════════════════════════════════

# ── Windows · WinForms popup via PowerShell ────────────────────

def _dialog_windows(tool_name: str, desc: str, explanation: str, priority: int) -> str:
    """Launch PowerShell WinForms popup; poll signal file for result."""
    # Write JSON description file (backward-compat: pipe format for old popup)
    with open(DESC_FILE, "w", encoding="utf-8") as fh:
        json.dump({
            "toolName": tool_name,
            "desc": desc,
            "explanation": explanation,
        }, fh, ensure_ascii=False)

    # Clean stale signal
    _rm_f(SIGNAL_FILE)

    ps1 = os.path.join(SCRIPT_DIR, "popups", "dialog_win.ps1")

    subprocess.Popen(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", ps1,
            "-DescFile", DESC_FILE,
            "-SignalFile", SIGNAL_FILE,
            "-Priority", str(priority),
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

def _dialog_macos(tool_name: str, desc: str, explanation: str, priority: int) -> str:
    """Native osascript dialog — blocks until user clicks."""
    cn_map = {"Bash": "终端命令", "Write": "写入文件", "Edit": "编辑文件"}
    cn_name = cn_map.get(tool_name, tool_name)

    # AppleScript string escaping: backslash + double-quote
    safe_desc = desc.replace("\\", "\\\\").replace('"', '\\"')
    safe_explain = explanation.replace("\\", "\\\\").replace('"', '\\"')

    icon = "stop" if priority >= 1 else "caution"
    label_pri = " [系统级]" if priority >= 1 else ""

    script = (
        'set theResult to button returned of (display dialog "Claude 需要执行: '
        f'{cn_name}{label_pri}\\n\\n{safe_desc}\\n\\n'
        f'📋 影响分析：{safe_explain}\\n\\n'
        '允许执行此操作吗？" '
        'with title "Claude Code - 权限确认" '
        f'buttons {{"拒绝", "允许"}} default button "允许" with icon {icon})\n'
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

def _dialog_linux(tool_name: str, desc: str, explanation: str, priority: int) -> str:
    """Try every available dialog backend; terminal prompt as last resort."""
    cn_map = {"Bash": "终端命令", "Write": "写入文件", "Edit": "编辑文件"}
    cn_name = cn_map.get(tool_name, tool_name)

    label_pri = " [系统级]" if priority >= 1 else ""
    title = "Claude Code - 权限确认" + label_pri
    text = (f"Claude 需要执行: {cn_name}{label_pri}\n\n"
            f"{desc}\n\n"
            f"━━ 影响分析 ━━\n{explanation}\n\n"
            f"允许执行此操作吗？")

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
        if priority >= 1:
            root.focus_force()
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

def show_dialog(tool_name: str, desc: str, explanation: str, priority: int = 0) -> str:
    """Show the right native dialog for the current OS.  Returns 'allow' | 'deny'."""
    plat = _platform()
    if plat == "windows":
        return _dialog_windows(tool_name, desc, explanation, priority)
    if plat == "macos":
        return _dialog_macos(tool_name, desc, explanation, priority)
    return _dialog_linux(tool_name, desc, explanation, priority)


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

    # 6. Translate → explain → confirm -----------------------------
    desc = translate(tool_name, cmd, tool_input)
    explanation = explain(tool_name, cmd, tool_input)
    priority = int(os.environ.get("CLAUDE_CN_POPUP_PRIORITY", "0"))
    result = show_dialog(tool_name, desc, explanation, priority)

    if result == "allow":
        _emit("allow", "user confirmed via popup")
    else:
        _emit("deny", "user denied via popup")


if __name__ == "__main__":
    main()

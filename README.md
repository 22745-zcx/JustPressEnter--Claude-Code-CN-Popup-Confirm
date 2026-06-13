# Chinese Permission Popup 中文权限确认

[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-brightgreen)](.)
[![Python](https://img.shields.io/badge/python-3.6%2B-blue)](.)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

为 **Claude Code** 提供中文自然语言权限确认弹窗。

## 为什么需要它？

Claude Code 默认的权限确认是**英文终端对话**：

```
Claude needs your permission to run: rm /tmp/test.txt
Allow? (y/n/always) █
```

对于中文用户来说：
- 难以快速判断操作的风险等级
- 裸命令不直观（`rm -rf` vs "强制递归删除"）
- 终端内交互容易被其他输出淹没

本 skill 替换为**中文弹窗**：

```
╔══════════════════════════════════════════╗
║  Claude Code - 权限确认                   ║
║                                          ║
║  Claude 需要执行: 终端命令                  ║
║  ┌──────────────────────────────────┐    ║
║  │ 强制递归删除：/tmp/build/         │    ║
║  └──────────────────────────────────┘    ║
║  允许执行此操作吗？                       ║
║                                          ║
║  [ 允许 (Enter) ]    [ 拒绝 (Esc) ]       ║
╚══════════════════════════════════════════╝
```

## 快速开始

```bash
# 克隆
git clone https://github.com/YOUR_USERNAME/chinese-permission.git
cd chinese-permission

# 安装（选一个）
./install.sh        # macOS / Linux
.\install.ps1       # Windows
```

重启 Claude Code，搞定。

## 特性

- 🇨🇳 **自然语言描述** — "删除文件/目录：/tmp/foo" 而非 `rm /tmp/foo`
- 🖥️ **跨平台原生体验**
  - Windows → WinForms 暗色主题弹窗
  - macOS → 原生 AppleScript 对话框
  - Linux → Zenity / KDialog / Tkinter 自适应
- ⚡ **智能过滤** — 80+ 安全命令自动放行，不弹窗
- 🎯 **精准拦截** — 只在真正危险时弹窗（删除、写入、编辑）

## 触发弹窗的操作

| 命令 | 弹窗内容 |
|------|---------|
| `rm /tmp/test.txt` | 删除文件/目录：/tmp/test.txt |
| `rm -rf /tmp/build/` | 强制递归删除：/tmp/build/ |
| `del /f important.doc` | 强制删除文件：important.doc |
| `Remove-Item -Recurse dir/` | 强制删除项目：dir/ |
| Write(file_path="/etc/config") | 写入文件：/etc/config |
| Edit(file_path="app.ts", old="...") | 编辑文件：app.ts - 替换「...」 |
| `mv /etc/hosts /tmp/` | 移动/重命名：/etc/hosts /tmp/ |

## 不弹窗的安全命令

`ls` `cat` `head` `git` `grep` `find` `node` `npm` `python` `pip` `go` `cargo`
`docker` `ps` `date` `curl` `wget` `cp` `mkdir` `tar` `zip` `chmod` ……

完整列表见 [`scripts/pretool_launcher.py`](scripts/pretool_launcher.py#L33-L45)。

## 架构

```
Claude Code 调用工具
  ↓
PreToolUse Hook (settings.json)
  ↓
pretool_launcher.py (Python)
  ├─ 安全工具? → 直接放行
  ├─ 安全命令? → 直接放行
  └─ 危险操作? → 翻译中文 → 弹窗确认
                    ↓
         ┌─────────┴─────────┐
         ↓                   ↓
      允许 → 执行          拒绝 → 阻止
```

## 手动配置

如果安装脚本失败，手动配置如下：

### 1. 复制文件
```bash
cp -r scripts/ ~/.claude/skills/chinese-permission/scripts/
cp SKILL.md ~/.claude/skills/chinese-permission/
```

### 2. 修改 `~/.claude/settings.json`

添加 PreToolUse hook：
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/chinese-permission/scripts/pretool_launcher.py",
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

> Windows 用户：把 `python3` 改为 `python`。

### 3. 修改 `~/.claude/settings.local.json`

在 `permissions.allow` 中添加：
```json
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
```

## 依赖

- Python 3.6+
- Windows: PowerShell（内置）
- macOS: osascript（内置）
- Linux: zenity（`apt install zenity`）或 kdialog

## 常见问题

**Q: 弹窗不出来？**
A: 检查 Python 版本 `python3 --version`，确保 ≥ 3.6。

**Q: Windows 弹窗乱码？**
A: 确保 `.ps1` 文件编码为 UTF-8 with BOM（安装脚本已处理）。

**Q: Linux 没有 zenity？**
A: 安装 `sudo apt install zenity`，或脚本会自动降级到 tkinter / 终端交互。

**Q: macOS 弹窗不是中文？**
A: macOS 系统语言设置不影响 osascript 弹窗按钮文字，已硬编码为中文。

**Q: 某个安全命令还是会弹窗？**
A: 编辑 `pretool_launcher.py`，在 `SAFE_COMMANDS` 中添加该命令。

**Q: 想自定义弹窗外观？**
A: Windows 用户编辑 `popups/dialog_win.ps1`；macOS/Linux 用户编辑 `pretool_launcher.py` 中的 `_dialog_macos` / `_dialog_linux`。

## 许可证

MIT © 22745-zcx

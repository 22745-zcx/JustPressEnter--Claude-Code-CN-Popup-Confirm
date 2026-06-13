# Windows WinForms confirmation popup
# Reads natural-language description from a file, shows dark-themed dialog,
# writes "allow" or "deny" to a signal file.
#
# Called by pretool_launcher.py with -DescFile <path> -SignalFile <path>

param(
    [string]$DescFile = "$env:TEMP\claude_pretool_desc.txt",
    [string]$SignalFile = "$env:TEMP\claude_pretool_signal.txt"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ── Read description ──────────────────────────────────────────
$toolName = ""
$desc = ""
if (Test-Path $DescFile) {
    $content = Get-Content $DescFile -Raw -Encoding UTF8
    $parts = $content -split '\|', 2
    $toolName = $parts[0]
    $desc = if ($parts.Count -gt 1) { $parts[1].Trim() } else { "" }
}

$cnMap = @{"Bash" = "终端命令"; "Write" = "写入文件"; "Edit" = "编辑文件"}
$cnName = if ($cnMap[$toolName]) { $cnMap[$toolName] } else { $toolName }

# ── Build UI ───────────────────────────────────────────────────
$form = New-Object System.Windows.Forms.Form
$form.Text = "Claude Code - 权限确认"
$form.Width = 550; $form.Height = 310
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.ControlBox = $false
$form.ShowInTaskbar = $false
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 30)
$form.KeyPreview = $true

# Title label
$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = "羲羲 需要执行: $cnName"
$lblTitle.Font = New-Object System.Drawing.Font("Microsoft YaHei", 12, [System.Drawing.FontStyle]::Bold)
$lblTitle.ForeColor = [System.Drawing.Color]::Cyan
$lblTitle.AutoSize = $true
$lblTitle.Location = New-Object System.Drawing.Point(30, 20)
$form.Controls.Add($lblTitle)

# Description textbox (read-only, looks like a code block)
$txtDesc = New-Object System.Windows.Forms.TextBox
$txtDesc.Text = $desc
$txtDesc.Font = New-Object System.Drawing.Font("Microsoft YaHei", 10)
$txtDesc.ForeColor = [System.Drawing.Color]::White
$txtDesc.BackColor = [System.Drawing.Color]::FromArgb(45, 45, 48)
$txtDesc.Multiline = $true
$txtDesc.ReadOnly = $true
$txtDesc.Width = 480; $txtDesc.Height = 80
$txtDesc.Location = New-Object System.Drawing.Point(30, 55)
$txtDesc.BorderStyle = "FixedSingle"
$form.Controls.Add($txtDesc)

# Question label
$lblQuestion = New-Object System.Windows.Forms.Label
$lblQuestion.Text = "允许执行此操作吗？"
$lblQuestion.Font = New-Object System.Drawing.Font("Microsoft YaHei", 10)
$lblQuestion.ForeColor = [System.Drawing.Color]::White
$lblQuestion.AutoSize = $true
$lblQuestion.Location = New-Object System.Drawing.Point(30, 150)
$form.Controls.Add($lblQuestion)

# ── Buttons ────────────────────────────────────────────────────

# Allow button (Enter)
$btnAllow = New-Object System.Windows.Forms.Button
$btnAllow.Text = "允许 (Enter)"
$btnAllow.Font = New-Object System.Drawing.Font("Microsoft YaHei", 11, [System.Drawing.FontStyle]::Bold)
$btnAllow.Width = 180; $btnAllow.Height = 45
$btnAllow.Location = New-Object System.Drawing.Point(55, 195)
$btnAllow.BackColor = [System.Drawing.Color]::FromArgb(0, 150, 100)
$btnAllow.ForeColor = [System.Drawing.Color]::White
$btnAllow.FlatStyle = "Flat"
$btnAllow.FlatAppearance.BorderSize = 0
$form.Controls.Add($btnAllow)
$form.AcceptButton = $btnAllow

# Deny button (Esc)
$btnDeny = New-Object System.Windows.Forms.Button
$btnDeny.Text = "拒绝 (Esc)"
$btnDeny.Font = New-Object System.Drawing.Font("Microsoft YaHei", 11)
$btnDeny.Width = 180; $btnDeny.Height = 45
$btnDeny.Location = New-Object System.Drawing.Point(275, 195)
$btnDeny.BackColor = [System.Drawing.Color]::FromArgb(180, 60, 60)
$btnDeny.ForeColor = [System.Drawing.Color]::White
$btnDeny.FlatStyle = "Flat"
$btnDeny.FlatAppearance.BorderSize = 0
$form.Controls.Add($btnDeny)

# ── Event handlers ─────────────────────────────────────────────
# ONLY write signal file — no SendKeys, no keybd_event, no simulation

$btnAllow.Add_Click({
    "allow" | Out-File $SignalFile -Encoding ascii -Force
    $this.FindForm().Close()
})

$btnDeny.Add_Click({
    "deny" | Out-File $SignalFile -Encoding ascii -Force
    $this.FindForm().Close()
})

$form.Add_KeyDown({
    param($sender, $e)
    if ($e.KeyCode -eq "Return" -or $e.KeyCode -eq "Enter") {
        "allow" | Out-File $SignalFile -Encoding ascii -Force
        $sender.Close()
    }
    if ($e.KeyCode -eq "Escape") {
        "deny" | Out-File $SignalFile -Encoding ascii -Force
        $sender.Close()
    }
})

# ── Show ───────────────────────────────────────────────────────
$form.ShowDialog() | Out-Null
$form.Dispose()

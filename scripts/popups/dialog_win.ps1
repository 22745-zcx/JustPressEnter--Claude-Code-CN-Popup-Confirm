# Windows WinForms confirmation popup
# Reads operation info from a JSON file, shows dark-themed dialog with
# natural-language description + impact explanation, writes "allow"/"deny" to signal.
#
# Called by pretool_launcher.py:
#   -DescFile <path>    JSON file with toolName, desc, explanation
#   -SignalFile <path>  File to write "allow" or "deny" into
#   -Priority <0|1>     0=normal (default), 1=system-modal

param(
    [string]$DescFile = "$env:TEMP\claude_pretool_desc.txt",
    [string]$SignalFile = "$env:TEMP\claude_pretool_signal.txt",
    [int]$Priority = 0
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ── Read operation info ────────────────────────────────────────
$toolName = ""
$desc = ""
$explanation = ""

if (Test-Path $DescFile) {
    $content = Get-Content $DescFile -Raw -Encoding UTF8
    # Try JSON first (new format), fall back to pipe-separated (old format)
    try {
        $data = $content | ConvertFrom-Json
        $toolName = $data.toolName
        $desc = if ($data.desc) { $data.desc } else { "" }
        $explanation = if ($data.explanation) { $data.explanation } else { "" }
    } catch {
        # Legacy pipe-separated format: toolName|desc
        $parts = $content -split '\|', 2
        $toolName = $parts[0]
        $desc = if ($parts.Count -gt 1) { $parts[1].Trim() } else { "" }
        $explanation = ""
    }
}

$cnMap = @{"Bash" = "终端命令"; "Write" = "写入文件"; "Edit" = "编辑文件"}
$cnName = if ($cnMap[$toolName]) { $cnMap[$toolName] } else { $toolName }

# ── Dynamic layout constants ───────────────────────────────────
if ($explanation) {
    $explainBoxHeight = 65
    $formHeight = 350
    $questionY = 220
    $btnY = 255
} else {
    $explainBoxHeight = 0
    $formHeight = 280
    $questionY = 140
    $btnY = 175
}
$explainY = 145

# ── Build form ─────────────────────────────────────────────────
$form = New-Object System.Windows.Forms.Form
$form.Text = "Claude Code - 权限确认" + $(if ($Priority -ge 1) { " [系统级]" } else { "" })
$form.Width = 560; $form.Height = $formHeight
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.ControlBox = $false
$form.ShowInTaskbar = $true
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 30)
$form.KeyPreview = $true

# ── Title label ────────────────────────────────────────────────
$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = "Claude 需要执行: $cnName" + $(if ($Priority -ge 1) { " [系统级]" } else { "" })
$lblTitle.Font = New-Object System.Drawing.Font("Microsoft YaHei", 12, [System.Drawing.FontStyle]::Bold)
$lblTitle.ForeColor = $(if ($Priority -ge 1) { [System.Drawing.Color]::OrangeRed } else { [System.Drawing.Color]::Cyan })
$lblTitle.AutoSize = $true
$lblTitle.Location = New-Object System.Drawing.Point(30, 20)
$form.Controls.Add($lblTitle)

# ── Description textbox (what will happen) ─────────────────────
$txtDesc = New-Object System.Windows.Forms.TextBox
$txtDesc.Text = $desc
$txtDesc.Font = New-Object System.Drawing.Font("Microsoft YaHei", 10)
$txtDesc.ForeColor = [System.Drawing.Color]::White
$txtDesc.BackColor = [System.Drawing.Color]::FromArgb(45, 45, 48)
$txtDesc.Multiline = $true; $txtDesc.ReadOnly = $true
$txtDesc.Width = 490; $txtDesc.Height = 60
$txtDesc.Location = New-Object System.Drawing.Point(30, 55)
$txtDesc.BorderStyle = "FixedSingle"
$form.Controls.Add($txtDesc)

# ── Explanation textbox (impact analysis) ──────────────────────
if ($explanation) {
    $lblExplain = New-Object System.Windows.Forms.Label
    $lblExplain.Text = "影响分析"
    $lblExplain.Font = New-Object System.Drawing.Font("Microsoft YaHei", 8.5, [System.Drawing.FontStyle]::Bold)
    $lblExplain.ForeColor = [System.Drawing.Color]::DarkGray
    $lblExplain.AutoSize = $true
    $lblExplain.Location = New-Object System.Drawing.Point(32, 122)
    $form.Controls.Add($lblExplain)

    $txtExplain = New-Object System.Windows.Forms.TextBox
    $txtExplain.Text = $explanation
    $txtExplain.Font = New-Object System.Drawing.Font("Microsoft YaHei", 9)
    $txtExplain.ForeColor = [System.Drawing.Color]::FromArgb(200, 200, 200)
    $txtExplain.BackColor = [System.Drawing.Color]::FromArgb(42, 42, 44)
    $txtExplain.Multiline = $true; $txtExplain.ReadOnly = $true
    $txtExplain.Width = 490; $txtExplain.Height = $explainBoxHeight
    $txtExplain.Location = New-Object System.Drawing.Point(30, $explainY)
    $txtExplain.BorderStyle = "FixedSingle"
    $txtExplain.ScrollBars = "Vertical"
    $form.Controls.Add($txtExplain)
}

# ── Question label ─────────────────────────────────────────────
$lblQuestion = New-Object System.Windows.Forms.Label
$lblQuestion.Text = "允许执行此操作吗？"
$lblQuestion.Font = New-Object System.Drawing.Font("Microsoft YaHei", 10)
$lblQuestion.ForeColor = [System.Drawing.Color]::White
$lblQuestion.AutoSize = $true
$lblQuestion.Location = New-Object System.Drawing.Point(30, $questionY)
$form.Controls.Add($lblQuestion)

# ── Allow button (Enter) ───────────────────────────────────────
$btnAllow = New-Object System.Windows.Forms.Button
$btnAllow.Text = "允许 (Enter)"
$btnAllow.Font = New-Object System.Drawing.Font("Microsoft YaHei", 11, [System.Drawing.FontStyle]::Bold)
$btnAllow.Width = 180; $btnAllow.Height = 45
$btnAllow.Location = New-Object System.Drawing.Point(55, $btnY)
$btnAllow.BackColor = [System.Drawing.Color]::FromArgb(0, 150, 100)
$btnAllow.ForeColor = [System.Drawing.Color]::White
$btnAllow.FlatStyle = "Flat"
$btnAllow.FlatAppearance.BorderSize = 0
$form.Controls.Add($btnAllow)
$form.AcceptButton = $btnAllow

# ── Deny button (Esc) ──────────────────────────────────────────
$btnDeny = New-Object System.Windows.Forms.Button
$btnDeny.Text = "拒绝 (Esc)"
$btnDeny.Font = New-Object System.Drawing.Font("Microsoft YaHei", 11)
$btnDeny.Width = 180; $btnDeny.Height = 45
$btnDeny.Location = New-Object System.Drawing.Point(275, $btnY)
$btnDeny.BackColor = [System.Drawing.Color]::FromArgb(180, 60, 60)
$btnDeny.ForeColor = [System.Drawing.Color]::White
$btnDeny.FlatStyle = "Flat"
$btnDeny.FlatAppearance.BorderSize = 0
$form.Controls.Add($btnDeny)

# ── Event handlers ─────────────────────────────────────────────

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

# ── System-modal: keep focus when priority >= 1 ────────────────
if ($Priority -ge 1) {
    $form.Add_Deactivate({
        $this.Activate()
    })
}

# ── Show ───────────────────────────────────────────────────────
$form.ShowDialog() | Out-Null
$form.Dispose()

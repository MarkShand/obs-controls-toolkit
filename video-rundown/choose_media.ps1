param(
    [string]$Label = "Link video folder",
    [switch]$FileOnly,
    [switch]$DropFile,
    [switch]$FolderOnly,
    [string]$InitialFolder
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
function Show-ModernFolderPicker([string]$Title, [IntPtr]$Owner, [string]$StartFolder) {
    if (-not ("RundownFolderPicker" -as [type])) {
        Add-Type -Path (Join-Path $PSScriptRoot "folder_picker.cs")
    }
    return [RundownFolderPicker]::Show($Title, $Owner, $StartFolder)
}

if ($FolderOnly) {
    $path = Show-ModernFolderPicker $Label ([IntPtr]::Zero) $InitialFolder
    if ($path) { [Console]::WriteLine($path) }
    exit
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[void][System.Windows.Forms.Application]::EnableVisualStyles()

if ($FileOnly) {
    $picker = [System.Windows.Forms.OpenFileDialog]::new()
    try {
        $picker.Title = $Label
        $picker.Filter = "Video files|*.mp4;*.ts;*.mov;*.flv;*.mkv;*.avi;*.gif;*.webm|All files|*.*"
        if ($picker.ShowDialog() -eq "OK") {
            [Console]::WriteLine($picker.FileName)
        }
    } finally {
        $picker.Dispose()
    }
    exit
}

$window = [System.Windows.Forms.Form]::new()
try {
    $window.Text = $Label
    $window.ClientSize = [System.Drawing.Size]::new(440, 155)
    $window.StartPosition = "CenterScreen"
    $window.FormBorderStyle = "FixedDialog"
    $window.MaximizeBox = $false
    $window.MinimizeBox = $false
    $window.TopMost = $true
    $window.AllowDrop = $true

    $prompt = [System.Windows.Forms.Label]::new()
    $prompt.Text = if ($DropFile) {
        "Drop one video from Explorer here, or choose it below."
    } else {
        "Drop a folder from Explorer here, or choose it below."
    }
    $prompt.AutoSize = $true
    $prompt.Location = [System.Drawing.Point]::new(18, 22)
    $window.Controls.Add($prompt)

    $browse = [System.Windows.Forms.Button]::new()
    $browse.Text = if ($DropFile) { "Browse files..." } else { "Browse folders..." }
    $browse.Size = [System.Drawing.Size]::new(140, 30)
    $browse.Location = [System.Drawing.Point]::new(18, 99)
    $browse.Add_Click({
        if ($DropFile) {
            $picker = [System.Windows.Forms.OpenFileDialog]::new()
            try {
                $picker.Title = $Label
                $picker.Filter = "Video files|*.mp4;*.ts;*.mov;*.flv;*.mkv;*.avi;*.gif;*.webm|All files|*.*"
                if ($picker.ShowDialog($window) -eq "OK") {
                    $window.Tag = $picker.FileName
                    $window.Close()
                }
            } finally {
                $picker.Dispose()
            }
        } else {
            $path = Show-ModernFolderPicker $Label $window.Handle
            if ($path) {
                $window.Tag = $path
                $window.Close()
            }
        }
    })
    $window.Controls.Add($browse)

    $cancel = [System.Windows.Forms.Button]::new()
    $cancel.Text = "Cancel"
    $cancel.Location = [System.Drawing.Point]::new(345, 103)
    $cancel.DialogResult = "Cancel"
    $window.Controls.Add($cancel)
    $window.CancelButton = $cancel

    function Test-SelectedPath($paths) {
        if ($paths.Count -ne 1) { return $false }
        if ($DropFile) { return [System.IO.File]::Exists($paths[0]) }
        return [System.IO.Directory]::Exists($paths[0])
    }
    $checkDrag = {
        param($sender, $eventArgs)
        $paths = $eventArgs.Data.GetData([System.Windows.Forms.DataFormats]::FileDrop)
        $eventArgs.Effect = if (Test-SelectedPath $paths) { "Link" } else { "None" }
    }
    $window.Add_DragEnter($checkDrag)
    $window.Add_DragOver($checkDrag)
    $window.Add_DragDrop({
        param($sender, $eventArgs)
        $paths = $eventArgs.Data.GetData([System.Windows.Forms.DataFormats]::FileDrop)
        if (Test-SelectedPath $paths) {
            $window.Tag = $paths[0]
            $window.Close()
        }
    })
    [void]$window.ShowDialog()
    if ($window.Tag) {
        [Console]::WriteLine($window.Tag)
    }
} finally {
    $window.Dispose()
}

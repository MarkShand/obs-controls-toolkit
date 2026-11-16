param(
    [string]$Label,
    [ValidateSet("folder", "video", "backup")]
    [string]$Kind,
    [string]$InitialFolder,
    [switch]$Multiple,
    [string]$Pattern
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -Path (Join-Path $PSScriptRoot "folder_picker.cs")
$paths = [RundownMediaPicker]::Show($Label, $InitialFolder, $Kind, $Multiple.IsPresent, $Pattern)
[Console]::WriteLine((ConvertTo-Json -InputObject @($paths) -Compress))

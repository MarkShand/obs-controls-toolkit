$ErrorActionPreference = 'Stop'
$uninstall = $args -contains '--uninstall'
$noBootstrap = $uninstall -or ($args -contains '--dry-run') -or ($args -contains '--help') -or ($args -contains '-h')
$operation = if ($uninstall) { 'Uninstall' } else { 'Setup' }

function Test-ToolkitPython([string] $Executable, [switch] $StandardLibraryOnly) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $false
    }
    $storeAliases = (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps').TrimEnd('\') + '\'
    if ($Executable.StartsWith($storeAliases, [StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    $probe = if ($StandardLibraryOnly) {
        'import sys; assert sys.version_info >= (3,10)'
    } else {
        'import sys, ensurepip, tkinter, venv; assert sys.version_info >= (3,10)'
    }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Executable -I -c $probe *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Find-ToolkitPython([switch] $StandardLibraryOnly) {
    $candidates = @(
        Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        Join-Path $env:LOCALAPPDATA 'OBS-Control-Toolkit\Python314\python.exe'
        $roots = @(
            'HKCU:\Software\Python\PythonCore',
            'HKLM:\Software\Python\PythonCore',
            'HKLM:\Software\WOW6432Node\Python\PythonCore'
        )
        foreach ($root in $roots) {
            foreach ($version in Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue) {
                $install = Get-Item -LiteralPath (Join-Path $version.PSPath 'InstallPath') -ErrorAction SilentlyContinue
                if ($install) {
                    $install.GetValue('ExecutablePath')
                    $directory = $install.GetValue('')
                    if ($directory) { Join-Path $directory 'python.exe' }
                }
            }
        }
        Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Source
        $parents = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
            $env:ProgramFiles,
            (Join-Path ($env:SystemDrive + '\') 'laragon\bin\python')
        )
        foreach ($parent in $parents) {
            foreach ($folder in Get-ChildItem -LiteralPath $parent -Filter 'Python*' -Directory -ErrorAction SilentlyContinue) {
                Join-Path $folder.FullName 'python.exe'
            }
        }
    )
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-ToolkitPython $candidate -StandardLibraryOnly:$StandardLibraryOnly) { return $candidate }
    }
}

function Install-ToolkitPython {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'This toolkit requires 64-bit Windows.'
    }

    # Use the standard x64 build with a published PyAV wheel and a pinned python.org checksum.
    $version = '3.14.10'
    $sha256 = '92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965'
    $url = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
    $temp = Join-Path ([IO.Path]::GetTempPath()) "obs-toolkit-python-$([Guid]::NewGuid())"
    $destination = Join-Path $env:LOCALAPPDATA 'OBS-Control-Toolkit\Python314'
    $log = Join-Path ([IO.Path]::GetTempPath()) 'OBS-Control-Toolkit-Python-install.log'
    New-Item -ItemType Directory -Path $temp | Out-Null
    $installer = Join-Path $temp 'python-installer.exe'
    try {
        Write-Host "Python with Tcl/Tk was not found. Downloading Python $version from python.org..."
        $previousProgress = $ProgressPreference
        try {
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $url -UseBasicParsing -OutFile $installer -TimeoutSec 180
        } finally {
            $ProgressPreference = $previousProgress
        }
        if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $sha256) {
            throw 'The Python download did not match its published checksum. Run Setup again to retry.'
        }
        Write-Host 'Installing Python for this Windows user...'
        $installerArguments = @(
            '/quiet', '/norestart', '/log', ('"{0}"' -f $log),
            'InstallAllUsers=0', ('TargetDir="{0}"' -f $destination),
            'Include_launcher=0', 'Include_pip=1', 'Include_tcltk=1',
            'Include_test=0', 'PrependPath=0', 'AssociateFiles=0', 'Shortcuts=0'
        )
        $result = Start-Process -FilePath $installer -ArgumentList $installerArguments -Wait -PassThru -WindowStyle Hidden
        $python = Join-Path $destination 'python.exe'
        if (($result.ExitCode -in (0, 3010)) -and (Test-ToolkitPython $python)) { return $python }
        if ($result.ExitCode -eq 3010) {
            throw 'Python setup requested a restart. Restart Windows and run Setup again.'
        }
        throw "Python setup could not finish (exit code $($result.ExitCode)). See $log"
    } finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $temp -ErrorAction SilentlyContinue
    }
}

function Start-LegacyToolkit([string] $Python) {
    $venv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-ToolkitPython $venv)) {
        & $Python -I -m venv (Join-Path $PSScriptRoot '.venv')
        if ($LASTEXITCODE) { return }
    }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $venv -I -c 'import obsws_python, send2trash, av' *> $null
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($LASTEXITCODE) {
        Write-Host 'Installing Video Rundown components...'
        & $venv -m pip install -r 'video-rundown\requirements.txt'
        if ($LASTEXITCODE) { return }
    }
    Write-Host 'First run: see README.md for the OBS scripts and dock URLs.'
    Write-Host 'Keep this window open while using Video Rundown.'
    & $venv 'video-rundown\video_rundown.py'
}

try {
    Set-Location -LiteralPath $PSScriptRoot
    $python = Find-ToolkitPython -StandardLibraryOnly:$noBootstrap
    if (-not $python) {
        if ($noBootstrap) { throw 'Python 3.10 or newer is needed to run this command.' }
        if (Get-Process -Name obs64,obs32,obs -ErrorAction SilentlyContinue) {
            throw 'Quit OBS completely before running Setup.'
        }
        $python = Install-ToolkitPython
    }
    Write-Host "Using Python at $python"
    $pythonDirectory = Split-Path -Parent $python
    $env:Path = "$pythonDirectory;$pythonDirectory\Scripts;$env:Path"
    if (Test-Path -LiteralPath 'setup_toolkit.py' -PathType Leaf) {
        & $python 'setup_toolkit.py' @args
    } elseif ($noBootstrap) {
        throw 'setup_toolkit.py was not found. Run the command from the complete toolkit folder.'
    } else {
        Start-LegacyToolkit $python
    }
    exit $LASTEXITCODE
} catch {
    Write-Host "$operation could not finish. $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

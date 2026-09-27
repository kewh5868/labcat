# Install only the native shell and fixed launcher resources for the current user.
# Docker continues to hold the application workspace; no credentials are copied.
[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\Labcat'),
    [switch]$NoShortcut
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-RegularFile {
    param([string]$Path)
    $item = Get-Item -Force -LiteralPath $Path -ErrorAction Stop
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Required installation file is not a regular file: $Path"
    }
}

function Assert-PlainDirectory {
    param([string]$Path)
    $item = Get-Item -Force -LiteralPath $Path -ErrorAction Stop
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Required installation directory is not a plain directory: $Path"
    }
}

if ($env:OS -cne 'Windows_NT') {
    throw 'Use this installer on Windows. Use scripts/install_desktop.sh on macOS or Linux.'
}
if (-not [IO.Path]::IsPathRooted($SourceRoot) -or -not [IO.Path]::IsPathRooted($Destination)) {
    throw 'Source and destination must be absolute local paths.'
}
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$Destination = [IO.Path]::GetFullPath($Destination).TrimEnd([char]92, [char]47)
if ($Destination -eq [IO.Path]::GetPathRoot($Destination) -or $Destination -eq $SourceRoot) {
    throw 'Choose a dedicated per-user application folder, not a drive root or the source checkout.'
}
Assert-PlainDirectory $SourceRoot
$destinationParent = Split-Path -Parent $Destination
[IO.Directory]::CreateDirectory($destinationParent) | Out-Null
Assert-PlainDirectory $destinationParent
$installMarker = '.labcat-desktop-install'
$installIdentity = 'labcat-desktop-v1'
if (Test-Path -LiteralPath $Destination) {
    Assert-PlainDirectory $Destination
    $existingMarker = Join-Path $Destination $installMarker
    if (-not (Test-Path -LiteralPath $existingMarker -PathType Leaf)) {
        throw 'The destination already exists and is not managed by this installer. Choose another destination or move it aside yourself.'
    }
    Assert-RegularFile $existingMarker
    if ([IO.File]::ReadAllText($existingMarker).Trim() -cne $installIdentity) {
        throw 'The destination has an unrecognized installation marker; it was not changed.'
    }
}
$launcherFiles = @('labcat.ps1', 'labcat.cmd', 'compose.yaml')
foreach ($name in $launcherFiles) { Assert-RegularFile (Join-Path $SourceRoot $name) }

$native = Join-Path $SourceRoot 'desktop-bin\Labcat.exe'
if (Test-Path -LiteralPath $native) {
    Assert-RegularFile $native
}
else {
    $desktopSource = Join-Path $SourceRoot 'desktop'
    foreach ($name in @('package.json', 'package-lock.json', 'Cargo.toml', 'Cargo.lock', 'tauri.conf.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $desktopSource $name) -PathType Leaf)) {
            throw 'This download has no native Windows shell or complete desktop source. Obtain a Windows desktop bundle or choose -Browser.'
        }
        Assert-RegularFile (Join-Path $desktopSource $name)
    }
    foreach ($command in @('node', 'npm', 'cargo')) {
        if ($null -eq (Get-Command $command -CommandType Application -ErrorAction SilentlyContinue)) {
            throw 'Building the Windows desktop shell requires Node.js/npm, Rust/Cargo and Visual Studio C++ Build Tools with the Windows SDK. Install the documented prerequisites, restart the terminal and retry, or choose -Browser.'
        }
    }
    if (-not [string]::IsNullOrEmpty($env:CARGO_BUILD_TARGET) -or -not [string]::IsNullOrEmpty($env:CARGO_TARGET_DIR)) {
        throw 'Unset CARGO_BUILD_TARGET and CARGO_TARGET_DIR for this native desktop install, or provide a matching desktop-bin\Labcat.exe.'
    }
    Write-Host 'Building the native Windows shell. Docker provides the backend; WebView2 must be available on Windows.'
    & npm ci --prefix $desktopSource --no-audit --no-fund | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency setup failed. Nothing was installed; check npm output and retry.' }
    & npm run build --prefix $desktopSource -- --no-bundle -- --locked | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw 'Desktop build failed. Check the Rust/MSVC C++ Build Tools and Windows SDK prerequisites; nothing was installed. You can choose -Browser.'
    }
    $native = Join-Path $desktopSource 'target\release\labcat-desktop.exe'
    Assert-RegularFile $native
}

$localCompose = Join-Path $SourceRoot 'compose.local.yaml'
$projectDirectory = $SourceRoot
$projectMarker = Join-Path $SourceRoot '.labcat-project-directory'
if (Test-Path -LiteralPath $projectMarker) {
    Assert-RegularFile $projectMarker
    $projectDirectory = [IO.File]::ReadAllText($projectMarker).TrimEnd([char]13, [char]10)
}
if ($projectDirectory -match '[\r\n]' -or -not [IO.Path]::IsPathRooted($projectDirectory) -or -not (Test-Path -LiteralPath $projectDirectory -PathType Container)) {
    throw 'The original deployment folder is unavailable. Restore it or reinstall from its new location.'
}
if (Test-Path -LiteralPath $localCompose) { Assert-RegularFile $localCompose }

$unique = [Guid]::NewGuid().ToString('N')
$stage = Join-Path $destinationParent ('.labcat-install-' + $unique)
$backup = Join-Path $destinationParent ('.labcat-previous-' + $unique)
$installed = $false
try {
    [IO.Directory]::CreateDirectory((Join-Path $stage 'launcher')) | Out-Null
    Copy-Item -LiteralPath $native -Destination (Join-Path $stage 'Labcat.exe')
    foreach ($name in $launcherFiles) {
        Copy-Item -LiteralPath (Join-Path $SourceRoot $name) -Destination (Join-Path $stage ('launcher\' + $name))
    }
    [IO.File]::WriteAllText((Join-Path $stage '.labcat-install-source'), "$SourceRoot`n", [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $stage $installMarker), "$installIdentity`n", [Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $localCompose -PathType Leaf) {
        Copy-Item -LiteralPath $localCompose -Destination (Join-Path $stage 'launcher\compose.local.yaml')
    }
    if ((Test-Path -LiteralPath $localCompose -PathType Leaf) -or (Test-Path -LiteralPath $projectMarker -PathType Leaf)) {
        [IO.File]::WriteAllText((Join-Path $stage 'launcher\.labcat-project-directory'), "$projectDirectory`n", [Text.UTF8Encoding]::new($false))
    }
    if (Test-Path -LiteralPath $Destination) { Move-Item -LiteralPath $Destination -Destination $backup }
    try {
        Move-Item -LiteralPath $stage -Destination $Destination
        $installed = $true
    }
    catch {
        if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $Destination }
        throw
    }
}
finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    if ($installed -and (Test-Path -LiteralPath $backup)) { Remove-Item -LiteralPath $backup -Recurse -Force }
}
$installedExecutable = Join-Path $Destination 'Labcat.exe'
if (-not $NoShortcut) {
    $programs = [Environment]::GetFolderPath('Programs')
    if ([string]::IsNullOrEmpty($programs)) { throw 'Labcat was installed, but the per-user Start menu is unavailable.' }
    [IO.Directory]::CreateDirectory($programs) | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $programs 'Labcat.lnk'))
    $shortcut.TargetPath = $installedExecutable
    $shortcut.WorkingDirectory = $Destination
    $shortcut.Description = 'Labcat materials research'
    $shortcut.Save()
}
Write-Host "Labcat desktop installed at $installedExecutable"

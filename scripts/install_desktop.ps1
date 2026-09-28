# Install only the native shell and fixed launcher resources for the current user.
# Docker continues to hold the application workspace; no credentials are copied.
[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\Labcat'),
    [switch]$NoShortcut,
    [switch]$CheckOnly,
    [switch]$PrebuiltOnly,
    [switch]$BuildSource
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Windows PowerShell initializes script paths after parameter defaults are evaluated.
if (-not $PSBoundParameters.ContainsKey('SourceRoot')) {
    $SourceRoot = Split-Path -Parent $PSScriptRoot
}

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
if (Test-Path -LiteralPath $destinationParent) { Assert-PlainDirectory $destinationParent }
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

function Show-Prerequisite {
    param([bool]$Met, [string]$Label, [string]$Fix)
    if ($Met) { Write-Host "  [met] $Label" }
    else {
        Write-Host "  [missing] $Label; $Fix"
        $script:missingPrerequisites += 1
    }
}

function Get-ToolVersion {
    param([string]$Name)
    $tool = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $tool) { return $null }
    try {
        $raw = (& $tool.Source --version 2>$null | Out-String)
        if ($LASTEXITCODE -eq 0 -and $raw -match '^\D*(\d+\.\d+\.\d+)') {
            return [version]$Matches[1]
        }
    }
    catch { }
    return $null
}

$native = Join-Path $SourceRoot 'desktop-bin\Labcat.exe'
if ($PrebuiltOnly -and $BuildSource) { throw 'Choose only one of -PrebuiltOnly and -BuildSource.' }
$needsBuild = $BuildSource -or -not (Test-Path -LiteralPath $native)
if ($PrebuiltOnly -and $needsBuild) {
    throw 'No matching prebuilt native app is available in desktop-bin. Obtain the matching Labcat desktop bundle, choose -Browser, or explicitly choose -Desktop to build from source. No source build was started.'
}
if (-not $needsBuild) { Assert-RegularFile $native }
$script:missingPrerequisites = 0
Write-Host 'Labcat native desktop prerequisites (Docker still provides the backend):'
# Microsoft documents these per-machine/per-user Evergreen Runtime registrations.
$webViewVersion = $null
foreach ($root in @('HKLM:\SOFTWARE\WOW6432Node', 'HKLM:\SOFTWARE', 'HKCU:\SOFTWARE')) {
    $registration = Get-ItemProperty -LiteralPath ($root + '\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') -Name pv -ErrorAction SilentlyContinue
    if ($null -ne $registration -and $registration.pv -match '^\d+\.\d+\.\d+\.\d+$' -and [version]$registration.pv -gt [version]'0.0.0.0') {
        $webViewVersion = [version]$registration.pv
        break
    }
}
Show-Prerequisite ($null -ne $webViewVersion) "Microsoft Edge WebView2 Runtime $webViewVersion" 'install the Microsoft WebView2 Evergreen Runtime'
if ($needsBuild) {
    foreach ($spec in @(@('node', '24'), @('npm', 'any'), @('cargo', '1.88'), @('rustc', '1.88'))) {
        $toolVersion = Get-ToolVersion $spec[0]
        $met = $null -ne $toolVersion
        if ($met -and $spec[1] -eq '24') { $met = $toolVersion.Major -eq 24 }
        if ($met -and $spec[1] -eq '1.88') { $met = $toolVersion -ge [version]'1.88.0' }
        $fix = if ($spec[0] -in @('node', 'npm')) { 'install Node.js 24 LTS with npm and restart your terminal' } else { 'install Rust/Cargo 1.88 or newer with the MSVC toolchain using rustup' }
        Show-Prerequisite $met ($spec[0] + ' ' + $(if ($null -eq $toolVersion) { 'not available' } else { $toolVersion })) $fix
    }
    Show-Prerequisite ([string]::IsNullOrEmpty($env:CARGO_BUILD_TARGET) -and [string]::IsNullOrEmpty($env:CARGO_TARGET_DIR)) 'native build target' 'Unset CARGO_BUILD_TARGET and CARGO_TARGET_DIR for this native desktop install'
    $desktopSource = Join-Path $SourceRoot 'desktop'
    foreach ($name in @('package.json', 'package-lock.json', 'Cargo.toml', 'Cargo.lock', 'tauri.conf.json')) {
        $file = Join-Path $desktopSource $name
        $exists = Test-Path -LiteralPath $file -PathType Leaf
        if ($exists) { Assert-RegularFile $file }
        Show-Prerequisite $exists "source file desktop/$name" 'use a complete checkout or matching Windows native bundle'
    }
    $rustHost = ''
    if ($null -ne (Get-Command rustc -CommandType Application -ErrorAction SilentlyContinue)) {
        try {
            $hostReport = (& rustc -vV 2>$null | Out-String)
            if ($LASTEXITCODE -eq 0 -and $hostReport -match '(?m)^host: ((x86_64|aarch64|i686)-pc-windows-msvc)\s*$') { $rustHost = $Matches[1] }
        }
        catch { }
    }
    Show-Prerequisite (-not [string]::IsNullOrEmpty($rustHost)) "MSVC Rust host $rustHost" 'run rustup default stable-msvc, then restart your terminal'
    $architecture = if ($rustHost.StartsWith('aarch64')) { 'arm64' } elseif ($rustHost.StartsWith('i686')) { 'x86' } else { 'x64' }
    $visualStudio = ''
    $vswhere = if ([string]::IsNullOrEmpty(${env:ProgramFiles(x86)})) { '' } else { Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe' }
    if (-not $vswhere -or -not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
        $vswhereCommand = Get-Command vswhere -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        $vswhere = if ($null -eq $vswhereCommand) { '' } else { $vswhereCommand.Source }
    }
    if ($vswhere -and (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
        try {
            # Drain native output before inspecting the exit code. Select-Object
            # in this pipeline can stop the process before LASTEXITCODE is set.
            $locations = @(& $vswhere -latest -products '*' -requiresAny -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 Microsoft.VisualStudio.Component.VC.Tools.ARM64 -property installationPath 2>$null)
            $locatorExitCode = $LASTEXITCODE
            if ($locatorExitCode -eq 0 -and $locations.Count -gt 0) {
                $visualStudio = [string]$locations[0]
            }
        }
        catch { $visualStudio = '' }
    }
    $compiler = @()
    if ($visualStudio -and (Test-Path -LiteralPath $visualStudio -PathType Container)) {
        $compiler = @(Get-ChildItem -Path (Join-Path $visualStudio "VC/Tools/MSVC/*/bin/Host*/$architecture/cl.exe") -File -ErrorAction SilentlyContinue | Where-Object { Test-Path -LiteralPath (Join-Path $_.DirectoryName 'link.exe') -PathType Leaf })
    }
    Show-Prerequisite ($compiler.Count -gt 0) "Visual Studio C++ Build Tools ($architecture compiler and linker)" 'install the Desktop development with C++ workload in Visual Studio Build Tools'
    $sdk = $null
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows Kits\Installed Roots')) {
        $registration = Get-ItemProperty -LiteralPath $key -Name KitsRoot10 -ErrorAction SilentlyContinue
        if ($null -ne $registration -and -not [string]::IsNullOrEmpty($registration.KitsRoot10)) { $sdk = $registration.KitsRoot10; break }
    }
    $sdkVersions = @()
    if ($sdk -and (Test-Path -LiteralPath $sdk -PathType Container)) {
        $sdkVersions = @(Get-ChildItem -LiteralPath (Join-Path $sdk 'Include') -Directory -ErrorAction SilentlyContinue | Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName 'um/Windows.h') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName 'ucrt/stdio.h') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $sdk "Lib/$($_.Name)/um/$architecture/kernel32.lib") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $sdk "Lib/$($_.Name)/ucrt/$architecture/ucrt.lib") -PathType Leaf)
        })
    }
    Show-Prerequisite ($sdkVersions.Count -gt 0) "Windows 10/11 SDK ($architecture headers and libraries)" 'add a Windows SDK in the Visual Studio Installer'
}
else {
    Write-Host '  [met] prebuilt native app; Node/npm, Rust/Cargo and native build tools are not needed'
}
if ($script:missingPrerequisites -gt 0) {
    throw "$script:missingPrerequisites prerequisite(s) missing. Install the items listed above and retry. See https://kewh5868.github.io/labcat/installation/#desktop-prerequisites. You can choose -Docker or -Browser without native build tools."
}
if ($CheckOnly) { Write-Host 'Desktop prerequisite check passed. Nothing was built or installed.'; return }
[IO.Directory]::CreateDirectory($destinationParent) | Out-Null
Assert-PlainDirectory $destinationParent
if ($needsBuild) {
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

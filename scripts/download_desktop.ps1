# Download only the official pinned native shell; Docker provides the backend.
[CmdletBinding()]
param([string]$SourceRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Windows PowerShell initializes script paths after parameter defaults are evaluated.
if (-not $PSBoundParameters.ContainsKey('SourceRoot')) {
    $SourceRoot = Split-Path -Parent $PSScriptRoot
}

function Assert-PlainPath {
    param([string]$Path, [bool]$Directory)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -ne $Directory -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The native download source or destination is not a plain local file/directory.'
    }
}

function Get-NativeArchiveDigest {
    param([string]$Path)
    # Framework hashing avoids any inherited PowerShell module search path.
    $hashStream = $null
    $sha256 = $null
    try {
        $hashStream = [IO.File]::OpenRead($Path)
        $sha256 = [Security.Cryptography.SHA256]::Create()
        return [BitConverter]::ToString($sha256.ComputeHash($hashStream)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        if ($null -ne $sha256) { $sha256.Dispose() }
        if ($null -ne $hashStream) { $hashStream.Dispose() }
    }
}

if ($env:OS -cne 'Windows_NT') { throw 'Use this downloader on Windows; use download_desktop.sh on Mac/Linux.' }
if (($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -and $env:PROCESSOR_ARCHITEW6432 -ne 'AMD64') -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
    throw 'A matching native Windows bundle is not available for this architecture. Choose -Browser or explicitly build with -Desktop.'
}
if (-not [IO.Path]::IsPathRooted($SourceRoot)) { throw 'SourceRoot must be an absolute local path.' }
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
Assert-PlainPath $SourceRoot $true
$manifestPath = Join-Path $SourceRoot 'scripts/desktop-release.tsv'
Assert-PlainPath $manifestPath $false
$target = 'x86_64-pc-windows-msvc'
$record = $null
foreach ($line in [IO.File]::ReadAllLines($manifestPath)) {
    if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith('#')) { continue }
    $fields = $line.Split([char]9)
    if ($fields.Count -ne 4) { throw 'The native release manifest is invalid.' }
    if ($fields[0] -cne $target) { continue }
    if ($null -ne $record -or $fields[1] -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$' -or $fields[2] -cne 'Labcat-x86_64-pc-windows-msvc.zip' -or $fields[3] -cnotmatch '^[a-f0-9]{64}$') {
        throw 'The native Windows release manifest is invalid.'
    }
    $record = $fields
}
if ($null -eq $record) { throw 'No pinned native Windows download is available. Choose -Browser or explicitly build with -Desktop.' }
$destination = Join-Path $SourceRoot 'desktop-bin'
if (Test-Path -LiteralPath $destination) { Assert-PlainPath $destination $true }
$native = Join-Path $destination 'Labcat.exe'
if (Test-Path -LiteralPath $native) {
    Assert-PlainPath $native $false
    Write-Host 'A native Windows shell is already available in desktop-bin; it was not changed.'
    return
}
$maximumBytes = 128MB
$stage = Join-Path $SourceRoot ('.labcat-desktop-download-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($stage) | Out-Null
$client = $null
$handler = $null
$response = $null
$incoming = $null
$outgoing = $null
$archive = $null
try {
    Add-Type -AssemblyName System.Net.Http
    Add-Type -AssemblyName System.IO.Compression
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $true
    $handler.MaxAutomaticRedirections = 5
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromMinutes(3)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd('Labcat-native-installer/1.0')
    $url = 'https://github.com/kewh5868/labcat/releases/download/' + $record[1] + '/' + $record[2]
    Write-Host ('Downloading the verified Labcat native Windows shell (' + $record[1] + ').')
    $response = $client.GetAsync($url, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
    $response.EnsureSuccessStatusCode() | Out-Null
    if ($response.RequestMessage.RequestUri.Scheme -cne ([Uri]$url).Scheme) { throw 'The native download redirect changed the required secure transport.' }
    if ($null -ne $response.Content.Headers.ContentLength -and $response.Content.Headers.ContentLength -gt $maximumBytes) { throw 'The native download exceeds the permitted size.' }
    $download = Join-Path $stage 'native.zip'
    $incoming = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
    $outgoing = [IO.File]::Create($download)
    $buffer = [byte[]]::new(65536)
    $total = 0L
    $deadline = [DateTime]::UtcNow.AddMinutes(3)
    while ($true) {
        $remaining = $deadline - [DateTime]::UtcNow
        if ($remaining.TotalMilliseconds -le 0) { throw 'The native download timed out.' }
        $read = $incoming.ReadAsync($buffer, 0, $buffer.Length)
        if (-not $read.Wait([int][Math]::Min($remaining.TotalMilliseconds, [int]::MaxValue))) { throw 'The native download timed out.' }
        $count = $read.GetAwaiter().GetResult()
        if ($count -eq 0) { break }
        $total += $count
        if ($total -gt $maximumBytes) { throw 'The native download exceeds the permitted size.' }
        $outgoing.Write($buffer, 0, $count)
    }
    $outgoing.Dispose(); $outgoing = $null
    $incoming.Dispose(); $incoming = $null
    if ($total -eq 0 -or (Get-NativeArchiveDigest $download) -cne $record[3]) { throw 'Native download checksum verification failed. Nothing was installed.' }
    $archive = [IO.Compression.ZipArchive]::new([IO.File]::OpenRead($download), [IO.Compression.ZipArchiveMode]::Read)
    if ($archive.Entries.Count -ne 1) { throw 'The native archive must contain exactly one Labcat.exe file.' }
    $entry = $archive.Entries[0]
    $fileKind = ($entry.ExternalAttributes -shr 16) -band 61440
    if ($entry.FullName -cne 'Labcat.exe' -or $fileKind -notin @(0, 32768) -or ($entry.ExternalAttributes -band 1040) -ne 0 -or $entry.Length -le 0 -or $entry.Length -gt $maximumBytes) { throw 'The native archive contains an invalid executable entry.' }
    $stagedNative = Join-Path $stage 'Labcat.exe'
    $incoming = $entry.Open()
    $outgoing = [IO.File]::Create($stagedNative)
    $total = 0L
    while (($count = $incoming.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $total += $count
        if ($total -gt $maximumBytes) { throw 'The native executable exceeds the permitted size.' }
        $outgoing.Write($buffer, 0, $count)
    }
    if ($total -ne $entry.Length) { throw 'The native executable is incomplete.' }
    $outgoing.Dispose(); $outgoing = $null
    $incoming.Dispose(); $incoming = $null
    $archive.Dispose(); $archive = $null
    if (-not (Test-Path -LiteralPath $destination)) { [IO.Directory]::CreateDirectory($destination) | Out-Null }
    Assert-PlainPath $destination $true
    # File.Move is atomic within this checkout and refuses to replace an existing app.
    [IO.File]::Move($stagedNative, $native)
    Write-Host 'Verified Labcat native shell downloaded. No Node, Rust or compiler was used.'
}
finally {
    foreach ($resource in @($outgoing, $incoming, $archive, $response, $client, $handler)) {
        if ($null -ne $resource) { $resource.Dispose() }
    }
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}

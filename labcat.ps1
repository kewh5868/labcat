# Start or manage the local Docker app without requiring Python or Node.
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status', 'logs', 'cli', 'help')]
    [string]$Action = 'start',
    [switch]$NoOpen,
    [switch]$Browser,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArguments = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ComposeFile = Join-Path $PSScriptRoot 'compose.yaml'
$ComposeArguments = @(
    'compose', '--project-name', 'labcat', '--file', $ComposeFile
)
# Preserve local deployment volumes and credential mounts on every lifecycle
# command, including when the bundled desktop app reopens this launcher.
$LocalComposeFile = Join-Path $PSScriptRoot 'compose.local.yaml'
if (Test-Path -LiteralPath $LocalComposeFile -PathType Leaf) {
    $ComposeArguments += @('--file', $LocalComposeFile)
}

function Write-CallbackNotice {
    [Console]::Error.WriteLine('Labcat: ChatGPT browser sign-in needs local port 1455. The app can still use other model connections.')
    [Console]::Error.WriteLine('To enable it later, make port 1455 available, set LABCAT_OAUTH_CALLBACK_PORT=1455, and run the launcher again.')
}

function Start-LabcatService {
    # Preserve a running dynamic-callback deployment when reopening the UI, so
    # Compose does not recreate it and discard its session credentials.
    if ([string]::IsNullOrEmpty($env:LABCAT_OAUTH_CALLBACK_PORT)) {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $existingBindings = @(& docker @ComposeArguments port labcat 1456 2>$null)
            $existingExit = $LASTEXITCODE
        }
        finally { $ErrorActionPreference = $previousPreference }
        if ($existingExit -eq 0 -and $existingBindings.Count -eq 1) {
            $existing = ([string]$existingBindings[0]).Trim()
            if ($existing -cmatch '\A127\.0\.0\.1:([0-9]{1,5})\z') {
                $port = [int]$Matches[1]
                if ($port -ge 1 -and $port -le 65535 -and $port -ne 1455) {
                    $env:LABCAT_OAUTH_CALLBACK_PORT = '0'
                }
            }
        }
    }
    $callback = $env:LABCAT_OAUTH_CALLBACK_PORT
    if ([string]::IsNullOrEmpty($callback)) { $callback = '1455' }
    if ($callback -cne '1455') { Write-CallbackNotice }
    # Windows PowerShell converts native stderr into ErrorRecord objects. Read
    # them without throwing so the exact callback collision can be classified.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $startupOutput = @(& docker @ComposeArguments up --detach --wait --wait-timeout 60 2>&1)
        $startupExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    foreach ($line in $startupOutput) { [Console]::Error.WriteLine([string]$line) }
    if ($startupExit -eq 0) { return }
    $diagnostic = $startupOutput -join "`n"
    $collision = $diagnostic -cmatch '(?:Bind for 127\.0\.0\.1:1455 failed: port is already allocated|127\.0\.0\.1:1455: bind: (?:address already in use|Only one usage of each socket address))'
    if ($callback -cne '1455' -or -not $collision) {
        throw 'The app could not start. Load its image archive, check Docker and inspect labcat.cmd logs.'
    }
    $env:LABCAT_OAUTH_CALLBACK_PORT = '0'
    [Console]::Error.WriteLine('Labcat: Port 1455 is already in use; retrying with a separate callback port.')
    Write-CallbackNotice
    try {
        $ErrorActionPreference = 'Continue'
        $retryOutput = @(& docker @ComposeArguments up --detach --wait --wait-timeout 60 2>&1)
        $retryExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    foreach ($line in $retryOutput) { [Console]::Error.WriteLine([string]$line) }
    if ($retryExit -ne 0) {
        throw 'The app could not start after selecting an alternate callback port. Check labcat.cmd logs.'
    }
}

function Get-LabcatUrl {
    $bindings = @(& docker @ComposeArguments port labcat 8000 2>$null)
    if ($LASTEXITCODE -ne 0 -or $bindings.Count -ne 1) {
        throw 'The app has no available web address. Run labcat.cmd start, or check labcat.cmd logs.'
    }
    $binding = ([string]$bindings[0]).Trim()
    if ($binding -cnotmatch '\A127\.0\.0\.1:([0-9]{1,5})\z') {
        throw 'Docker returned an unexpected web address. The launcher requires a single local-only port.'
    }
    $portNumber = [int]$Matches[1]
    if ($portNumber -lt 1 -or $portNumber -gt 65535) {
        throw 'Docker returned an invalid web port. Check labcat.cmd logs.'
    }
    return "http://127.0.0.1:$portNumber/"
}

function Open-LabcatWindow {
    param([string]$Url)

    $desktopExecutable = Join-Path $PSScriptRoot 'desktop-bin\Labcat.exe'
    if (-not $Browser -and (Test-Path -LiteralPath $desktopExecutable -PathType Leaf)) {
        try {
            Start-Process -FilePath $desktopExecutable -ArgumentList @('--url', $Url) | Out-Null
            return
        }
        catch {
            Write-Warning 'The desktop application could not be opened. Opening your default browser instead.'
        }
    }
    try {
        Start-Process -FilePath $Url | Out-Null
    }
    catch {
        Write-Warning "The app is running, but a browser could not be opened. Open $Url manually."
    }
}

try {
    if ($Action -eq 'help') {
        Write-Host 'Usage: labcat.cmd [start|stop|status|logs] [-Browser|-NoOpen]'
        Write-Host '       labcat.cmd cli [--offline] [application arguments, e.g. status --format json]'
        Write-Host 'CLI research uses the running application account. Complete model setup first.'
        Write-Host '--offline disables container networking; authenticated research requires network access.'
        exit 0
    }
    if ($Action -ne 'cli' -and $CliArguments.Count -gt 0) {
        throw 'Extra arguments are supported only after cli. Use start, stop, status, logs, or cli followed by command-line arguments.'
    }
    if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) {
        throw 'Keep labcat.ps1 and compose.yaml together in the installation folder.'
    }
    if ($null -eq (Get-Command docker -CommandType Application -ErrorAction SilentlyContinue)) {
        throw 'Docker is not installed or is not on PATH. Install Docker Desktop, start it, and retry.'
    }
    try {
        $dockerSystem = @(& docker info --format '{{.OSType}}' 2>$null)
        $dockerInfoExit = $LASTEXITCODE
    }
    catch {
        throw 'Docker is not ready. Start Docker Desktop, wait for its engine to start, and retry.'
    }
    if ($dockerInfoExit -ne 0) {
        throw 'Docker is not ready. Start Docker Desktop, wait for its engine to start, and retry.'
    }
    if ($dockerSystem.Count -ne 1 -or ([string]$dockerSystem[0]).Trim() -ne 'linux') {
        throw 'This image needs Linux containers. Switch Docker Desktop to Linux containers and retry.'
    }
    try {
        & docker compose version *> $null
        $composeVersionExit = $LASTEXITCODE
    }
    catch {
        throw 'Docker Compose is unavailable. Update Docker Desktop to include Compose with --wait support.'
    }
    if ($composeVersionExit -ne 0) {
        throw 'Docker Compose is unavailable. Update Docker Desktop to include Compose with --wait support.'
    }

    # A remote daemon cannot provide a window at this machine's loopback URL.
    # DOCKER_CONTEXT takes precedence over DOCKER_HOST in the Docker CLI.
    if (-not [string]::IsNullOrEmpty($env:DOCKER_CONTEXT) -or [string]::IsNullOrEmpty($env:DOCKER_HOST)) {
        try {
            $contextEndpoints = @(& docker context inspect --format '{{.Endpoints.docker.Host}}' 2>$null)
            $contextExit = $LASTEXITCODE
        }
        catch {
            throw 'Cannot inspect the Docker context. Select your local Docker Desktop/Engine context and retry.'
        }
        if ($contextExit -ne 0 -or $contextEndpoints.Count -ne 1) {
            throw 'Cannot inspect the Docker context. Select your local Docker Desktop/Engine context and retry.'
        }
        $dockerEndpoint = ([string]$contextEndpoints[0]).Trim()
    }
    else {
        $dockerEndpoint = $env:DOCKER_HOST
    }
    if ($dockerEndpoint -cnotmatch '\A(?:unix|npipe)://') {
        throw 'The desktop launcher requires a local Docker context. Select your local Docker Desktop/Engine context first.'
    }

    switch ($Action) {
        'cli' {
            $cliNetwork = 'bridge'
            if ($CliArguments.Count -gt 0 -and $CliArguments[0] -ceq '--offline') {
                $cliNetwork = 'none'
                $CliArguments = @($CliArguments | Select-Object -Skip 1)
            }
            if ($CliArguments.Count -eq 0) {
                $CliArguments = @('status')
            }
            if ($cliNetwork -ne 'none' -and $CliArguments[0] -ceq 'research') {
                Start-LabcatService
                $researchArguments = @($CliArguments | Select-Object -Skip 1)
                & docker @ComposeArguments exec --no-TTY labcat labcat research --server @researchArguments
                if ($LASTEXITCODE -ne 0) {
                    throw 'Research was not completed. Check application setup, unlock credentials and retry.'
                }
                break
            }
            $isolatedRunArguments = @(
                'run', '--rm', '--pull', 'never', '--network', $cliNetwork,
                '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--init',
                '--tmpfs', '/tmp:size=64m,mode=1777',
                '--tmpfs', '/var/lib/labcat:size=64m,uid=10001,gid=10001,mode=0700',
                'labcat:0.1.0.dev0'
            )
            & docker @isolatedRunArguments @CliArguments
            if ($LASTEXITCODE -ne 0) {
                throw 'The command-line app failed. Load the supplied image archive and check the command arguments.'
            }
        }
        'start' {
            Start-LabcatService
            $appUrl = Get-LabcatUrl
            Write-Host "Labcat is running at $appUrl"
            Write-Host 'Run this launcher again to reopen it. Use labcat.cmd stop to stop it.'
            if (-not $NoOpen) {
                Open-LabcatWindow $appUrl
            }
        }
        'stop' {
            & docker @ComposeArguments stop
            if ($LASTEXITCODE -ne 0) {
                throw 'The app could not be stopped. Check Docker Desktop and retry.'
            }
            Write-Host 'Labcat is stopped.'
        }
        'status' {
            & docker @ComposeArguments ps
            if ($LASTEXITCODE -ne 0) {
                throw 'The app status could not be read. Check Docker Desktop and retry.'
            }
            $runningIds = @(& docker @ComposeArguments ps --status running --quiet labcat)
            if ($LASTEXITCODE -ne 0) {
                throw 'The app status could not be read. Check Docker Desktop and retry.'
            }
            if ($runningIds.Count -gt 0) {
                $appUrl = Get-LabcatUrl
                Write-Host "Labcat address: $appUrl"
            }
            else {
                Write-Host 'Labcat is stopped. Run labcat.cmd start to start it.'
            }
        }
        'logs' {
            & docker @ComposeArguments logs --tail 100 labcat
            if ($LASTEXITCODE -ne 0) {
                throw 'The app logs could not be read. Check Docker Desktop and retry.'
            }
        }
    }
    exit 0
}
catch {
    [Console]::Error.WriteLine("Labcat: $($_.Exception.Message)")
    exit 1
}

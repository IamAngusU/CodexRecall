[CmdletBinding()]
param(
    [switch]$InstallMcp,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'

function Find-Python {
    $candidates = @()
    foreach ($name in @('py.exe', 'python3.exe', 'python.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            $arguments = if ($name -eq 'py.exe') { @('-3') } else { @() }
            $candidates += [pscustomobject]@{ File = $command.Source; Args = $arguments }
        }
    }

    $userPythonRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $userPythonRoot) {
        $installed = Get-ChildItem -LiteralPath $userPythonRoot -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending
        foreach ($path in $installed) {
            $candidates += [pscustomobject]@{ File = $path.FullName; Args = @() }
        }
    }
    foreach ($path in @(
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\python3.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\python.exe')
    )) {
        if (Test-Path -LiteralPath $path) {
            $candidates += [pscustomobject]@{ File = $path; Args = @() }
        }
    }

    foreach ($candidate in $candidates) {
        try {
            $version = & $candidate.File @($candidate.Args) -c 'import sys; print(str(sys.version_info.major)+chr(46)+str(sys.version_info.minor))' 2>$null
            if ([version]$version -ge [version]'3.10') {
                return [pscustomobject]@{ File = $candidate.File; Args = $candidate.Args; Version = $version }
            }
        } catch { }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host 'CodexRecall needs Python 3.10 or newer.'
    Write-Host 'Planned download: Python.Python.3.13 via Microsoft WinGet from the Python Software Foundation package.'
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'Python was not found and WinGet is unavailable. Install Python 3.10+ and run this installer again.'
    }
    if (-not $Yes) {
        if ([Console]::IsInputRedirected) {
            throw 'Download approval is required. Run the command in an interactive terminal or pass -Yes explicitly.'
        }
        $answer = Read-Host 'Install Python 3.13 now? [y/N]'
        if ($answer -notmatch '^(y|yes|j|ja)$') { throw 'Installation cancelled; nothing was downloaded.' }
    }
    & winget.exe install --id Python.Python.3.13 --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python installation failed with exit code $LASTEXITCODE" }
    $python = Find-Python
    if (-not $python) { throw 'Python was installed but is not available in this terminal yet. Open a new terminal and rerun install.ps1.' }
}

$repoRoot = if ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { $null }
$source = if ($repoRoot -and (Test-Path -LiteralPath (Join-Path $repoRoot 'pyproject.toml'))) {
    $repoRoot
} else {
    'https://github.com/IamAngusU/CodexRecall/archive/refs/tags/v0.1.1.zip'
}

Write-Host "Python $($python.Version): $($python.File)"
Write-Host "Installing CodexRecall from: $source"
& $python.File @($python.Args) -m pip install --user --upgrade $source
if ($LASTEXITCODE -ne 0) { throw "CodexRecall installation failed with exit code $LASTEXITCODE" }

if ($InstallMcp) {
    & $python.File @($python.Args) -m codex_recall install-mcp
    if ($LASTEXITCODE -ne 0) { throw "MCP registration failed with exit code $LASTEXITCODE" }
}

Write-Host ''
Write-Host 'CodexRecall installed.' -ForegroundColor Green
$launcher = @($python.File) + @($python.Args) + @('-m', 'codex_recall')
Write-Host ('Run: ' + ($launcher -join ' '))

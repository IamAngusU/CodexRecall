[CmdletBinding()]
param(
    [switch]$InstallMcp,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'

function Find-Python {
    foreach ($candidate in @(
        @{ File = 'py.exe'; Args = @('-3') },
        @{ File = 'python3.exe'; Args = @() },
        @{ File = 'python.exe'; Args = @() }
    )) {
        $command = Get-Command $candidate.File -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        try {
            $version = & $command.Source @($candidate.Args) -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null
            if ([version]$version -ge [version]'3.10') {
                return [pscustomobject]@{ File = $command.Source; Args = $candidate.Args; Version = $version }
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
    'https://github.com/IamAngusU/CodexRecall/archive/refs/heads/main.zip'
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
Write-Host "Run: $($python.File) $($python.Args -join ' ') -m codex_recall"

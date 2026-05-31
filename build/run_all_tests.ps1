param(
    [switch]$SkipSync,
    [string[]]$PytestArgs = @()
)

$ErrorActionPreference = 'Stop'
$env:UV_SYSTEM_CERTS = 'true'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $repoRoot

if (-not $SkipSync) {
    Write-Host 'Syncing dev dependencies with uv...'
    uv sync --all-packages --group dev
}

Write-Host 'Running strict pyright...'
uv run pyright -p pyrightconfig.strict.json

if ($PytestArgs.Count -eq 0) {
    Write-Host 'Running pytest with default project settings...'
    uv run pytest
}
else {
    Write-Host 'Running pytest with custom arguments...'
    uv run pytest @PytestArgs
}
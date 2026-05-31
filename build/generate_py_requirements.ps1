# Run this to update uv lockfile and .pre-commit-config.yaml to latest published
# versions of packages.

$env:UV_SYSTEM_CERTS = 'true'

& $($PsScriptRoot + '\..\setup_venv.ps1')

Write-Host 'Updating uv lockfile...'
uv lock --upgrade

& $($PsScriptRoot + '\..\setup_venv.ps1')

Write-Host 'Updating pre-commit...'
pre-commit autoupdate

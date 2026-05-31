# This can be run to set up your local machine with all requirements (or update them)

Write-Host ''
Write-Host 'Please wait, installing/upgrading environment... (this may take a few minutes)'
Write-Host ''

# remove any existing venv to ensure a clean install
if (Test-Path env:VIRTUAL_ENV) { deactivate }
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue venv

# install/upgrade uv
winget install --id=astral-sh.uv -e

# shell completion for uv and uvx
if (!(Test-Path -Path $PROFILE)) {
  New-Item -ItemType File -Path $PROFILE -Force
}
$completionLine = '(& uv generate-shell-completion powershell) | Out-String | Invoke-Expression'
if (-not (Get-Content $PROFILE | Select-String -SimpleMatch $completionLine)) {
  Add-Content -Path $PROFILE -Value $completionLine
}
$completionLine = '(& uvx --generate-shell-completion powershell) | Out-String | Invoke-Expression'
if (-not (Get-Content $PROFILE | Select-String -SimpleMatch $completionLine)) {
  Add-Content -Path $PROFILE -Value $completionLine
}

$hasGit = $false
try {
  git -v | Out-Null
  $hasGit = $true
}
catch {
  Write-Host 'Git not available.'
}
if ($hasGit) {
  # git needs to use Windows SSL to work easily with ssl intercept
  git config --global http.sslbackend schannel
}

# Read desired Python version from .python-version
$PY_VERSION=$(Get-Content .python-version)

# Try to execute 'uv' and show a message if it fails
try {
  uv --version | Out-Null
}
catch {
  # Display active user and system PATH values as lists
  Write-Host 'User PATH:'
  $userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
  $userPath.Split(';') | ForEach-Object { Write-Host "  $_" }
  Write-Host ''
  Write-Host 'System PATH:'
  $systemPath = [Environment]::GetEnvironmentVariable('PATH', 'Machine')
  $systemPath.Split(';') | ForEach-Object { Write-Host "  $_" }
  Write-Host ''
  Write-Host 'If this was your first time running setup_venv, you may need to reboot or at least close your open terminals and try again.'
  Write-Host ''
  Write-Host 'uv not found.  Setup unsuccessful.'
  Write-Host ''
  exit 1
}

$env:UV_SYSTEM_CERTS = 'true'
# Install that Python version and upgrade to latest patch
uv python install $PY_VERSION --force
uv python upgrade --preview-features python-upgrade

# create venv if it doesn't exist
if (-not (Test-Path -Path '.venv')) {
    uv venv --python $PY_VERSION
}
# activate venv
.venv\Scripts\activate

# install/upgrade all dependencies
uv sync
# install the local packages in editable mode
uv pip install -e ./configtool-client -e ./configtool-secrets

Write-Host ''
Write-Host 'Completed environment setup.'
Write-Host ''

param(
    [string]$RepoPath = $PSScriptRoot,
    [string]$SourceBranch = "main",
    [string]$TargetBranch = "release",
    [string]$Message = "Sync main into release (squashed)`n`nAll changes present in main and missing from release are included in this single commit."
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path $RepoPath).Path

# Ensure we're in a git repo and both branches exist.
git -C $repo rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Not a git repository: $repo"
}

git -C $repo rev-parse --verify $SourceBranch *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Source branch '$SourceBranch' does not exist in $repo"
}

git -C $repo rev-parse --verify $TargetBranch *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Target branch '$TargetBranch' does not exist in $repo"
}

$current = (git -C $repo branch --show-current).Trim()
$tree = (git -C $repo rev-parse "$SourceBranch`^{tree}").Trim()
$parent = (git -C $repo rev-parse $TargetBranch).Trim()

$newCommit = ($Message | git -C $repo commit-tree $tree -p $parent).Trim()

if ($current -eq $TargetBranch) {
    git -C $repo reset --hard $newCommit
} else {
    git -C $repo branch -f $TargetBranch $newCommit
}

Write-Host "Updated '$TargetBranch' with a single squashed sync commit: $newCommit"
Write-Host ""
Write-Host "Recent commits on ${TargetBranch}:"
git -C $repo log --oneline --decorate -n 3 $TargetBranch

Write-Host ""
Write-Host "Diff check ($TargetBranch..$SourceBranch):"
git -C $repo diff --name-status "$TargetBranch..$SourceBranch"

Write-Host ""
Write-Host "Diff check ($SourceBranch..$TargetBranch):"
git -C $repo diff --name-status "$SourceBranch..$TargetBranch"

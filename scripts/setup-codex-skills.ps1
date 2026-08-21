param(
    [string]$RepositoryRoot = ""
)

$ErrorActionPreference = "Stop"

function Get-ReparseTargetPath {
    param([System.IO.FileSystemInfo]$Item)

    $rawTarget = @($Item.Target)[0]
    if (-not $rawTarget) {
        throw "Unable to resolve reparse target: $($Item.FullName)"
    }
    if ([IO.Path]::IsPathRooted($rawTarget)) {
        return [IO.Path]::GetFullPath($rawTarget)
    }
    return [IO.Path]::GetFullPath((Join-Path $Item.Parent.FullName $rawTarget))
}

if ($RepositoryRoot) {
    $root = [IO.Path]::GetFullPath($RepositoryRoot)
} else {
    $gitRoot = $null
    try {
        $candidateRoot = git rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -eq 0 -and $candidateRoot) {
            $gitRoot = $candidateRoot.Trim()
        }
    } catch {
        $gitRoot = $null
    }
    $root = if ($gitRoot) {
        [IO.Path]::GetFullPath($gitRoot)
    } else {
        [IO.Path]::GetFullPath((Get-Location).Path)
    }
}

$source = Join-Path $root ".ai\skills"
$parent = Join-Path $root ".agents"
$dest = Join-Path $parent "skills"

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Canonical skill directory not found: $source"
}

New-Item -ItemType Directory -Force -Path $parent | Out-Null

$destItem = Get-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
if ($destItem -and (($destItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
    $resolvedDest = Get-ReparseTargetPath -Item $destItem
    if ([StringComparer]::OrdinalIgnoreCase.Equals($resolvedDest, [IO.Path]::GetFullPath($source))) {
        Write-Host "Legacy Codex skill bridge is already configured: $dest -> $source"
        exit 0
    }
    throw "$dest is a reparse point with an unexpected target. Review it manually."
}
if ($destItem -and -not $destItem.PSIsContainer) {
    throw "$dest exists and is not a directory. Review it manually."
}
if (-not $destItem) {
    New-Item -ItemType Directory -Path $dest | Out-Null
}

$created = 0
$reused = 0
$canonicalSkills = @(Get-ChildItem -LiteralPath $source -Directory | Where-Object {
    Test-Path -LiteralPath (Join-Path $_.FullName "SKILL.md") -PathType Leaf
})
if ($canonicalSkills.Count -eq 0) {
    throw "No canonical SKILL.md packages found under $source"
}

foreach ($skill in $canonicalSkills) {
    $discovered = Join-Path $dest $skill.Name
    $discoveredItem = Get-Item -LiteralPath $discovered -Force -ErrorAction SilentlyContinue
    if ($discoveredItem) {
        if (($discoveredItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
            throw "Discovery collision for '$($skill.Name)': $discovered is not a reparse point."
        }
        $resolvedTarget = Get-ReparseTargetPath -Item $discoveredItem
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals(
            $resolvedTarget,
            [IO.Path]::GetFullPath($skill.FullName)
        )) {
            throw "Discovery collision for '$($skill.Name)': $discovered targets $resolvedTarget."
        }
        $reused += 1
        continue
    }

    New-Item -ItemType Junction -Path $discovered -Target $skill.FullName | Out-Null
    $created += 1
}

$canonicalNames = @($canonicalSkills | ForEach-Object { $_.Name })
$external = @(Get-ChildItem -LiteralPath $dest -Directory | Where-Object {
    $canonicalNames -notcontains $_.Name
} | ForEach-Object { $_.Name })

Write-Host "Codex skill overlay configured at $dest ($created created, $reused reused)."
if ($external.Count -gt 0) {
    Write-Host "Preserved external discovery entries: $($external -join ', ')."
}
Write-Host "Restart Codex/VS Code if /skills does not refresh automatically."

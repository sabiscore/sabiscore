$ErrorActionPreference = "Stop"

try {
    $root = (git rev-parse --show-toplevel).Trim()
} catch {
    $root = (Get-Location).Path
}

$source = Join-Path $root ".ai\skills"
$parent = Join-Path $root ".agents"
$dest = Join-Path $parent "skills"

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Canonical skill directory not found: $source"
}

New-Item -ItemType Directory -Force -Path $parent | Out-Null

if (Test-Path -LiteralPath $dest) {
    $destItem = Get-Item -LiteralPath $dest -Force
    if (($destItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        $resolvedDest = $destItem.Target
        if ($resolvedDest -and ([IO.Path]::GetFullPath($resolvedDest) -eq [IO.Path]::GetFullPath($source))) {
            Write-Host "Codex skill junction is already configured: $dest -> $source"
            exit 0
        }
        throw "$dest is a reparse point with an unexpected target. Remove it manually after review."
    }

    # Migrate the old checked-in partial copy only when every file is an exact
    # duplicate of the canonical source. Any local customization stops here.
    $legacyFiles = @(Get-ChildItem -LiteralPath $dest -Recurse -File)
    foreach ($legacyFile in $legacyFiles) {
        $relative = [IO.Path]::GetRelativePath($dest, $legacyFile.FullName)
        $canonicalFile = Join-Path $source $relative
        if (-not (Test-Path -LiteralPath $canonicalFile -PathType Leaf)) {
            throw "Legacy bridge contains a non-canonical file: $relative"
        }
        if ((Get-FileHash -LiteralPath $legacyFile.FullName).Hash -ne (Get-FileHash -LiteralPath $canonicalFile).Hash) {
            throw "Legacy bridge contains a locally modified file: $relative"
        }
    }

    $expectedDest = [IO.Path]::GetFullPath((Join-Path $root ".agents\skills"))
    if ([IO.Path]::GetFullPath($dest) -ne $expectedDest) {
        throw "Refusing to replace unexpected bridge path: $dest"
    }
    Remove-Item -LiteralPath $dest -Recurse -Force
}

New-Item -ItemType Junction -Path $dest -Target $source | Out-Null
Write-Host "Created Codex skill junction: $dest -> $source"
Write-Host "Restart Codex/VS Code if /skills does not refresh automatically."

param(
    [string]$Branch = "master",
    [switch]$NoWatch
)

$ErrorActionPreference = "Stop"

function Assert-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

Assert-Command "gh"

Write-Host "Checking GitHub authentication..."
gh auth status | Out-Host

$workflowName = "CI - Canonical Platform"

Write-Host "Dispatching '$workflowName' on branch '$Branch'..."
gh workflow run "$workflowName" --ref "$Branch"

Start-Sleep -Seconds 3

$runJson = gh run list --workflow "$workflowName" --branch "$Branch" --limit 1 --json databaseId,displayTitle,headBranch,headSha,status,conclusion,url,createdAt
$run = ($runJson | ConvertFrom-Json | Select-Object -First 1)

if (-not $run) {
    throw "Failed to resolve the newly dispatched workflow run."
}

Write-Host "Run detected:"
Write-Host "  ID        : $($run.databaseId)"
Write-Host "  Branch    : $($run.headBranch)"
Write-Host "  Commit    : $($run.headSha)"
Write-Host "  Status    : $($run.status)"
Write-Host "  Conclusion: $($run.conclusion)"
Write-Host "  URL       : $($run.url)"

if ($NoWatch) {
    exit 0
}

Write-Host "Watching workflow run until completion..."
gh run watch $run.databaseId --exit-status

$finalJson = gh run view $run.databaseId --json databaseId,status,conclusion,url,headSha,headBranch,createdAt,updatedAt
$final = $finalJson | ConvertFrom-Json

Write-Host "Final run state:"
Write-Host "  ID        : $($final.databaseId)"
Write-Host "  Branch    : $($final.headBranch)"
Write-Host "  Commit    : $($final.headSha)"
Write-Host "  Status    : $($final.status)"
Write-Host "  Conclusion: $($final.conclusion)"
Write-Host "  URL       : $($final.url)"

if ($final.conclusion -ne "success") {
    throw "Canonical Linux CI did not succeed. Conclusion: $($final.conclusion)."
}

Write-Host "Canonical Linux CI completed successfully."
param(
    [Parameter(Mandatory = $true)]
    [string]$TaskPacket,

    [Parameter(Mandatory = $true)]
    [string]$Output,

    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\.." )).Path,
    [string]$GeminiBinary = "gemini",
    [string]$Model = "",
    [ValidateSet("default", "auto_edit", "yolo", "plan")]
    [string]$ApprovalMode = "auto_edit",
    [int]$TimeoutSeconds = 1800,
    [int]$MaxRepairAttempts = 1,
    [int]$LocalCheckTimeoutSeconds = 900,
    [switch]$SkipLocalRequiredChecks,
    [switch]$DryRun
)

$pythonScript = Join-Path $PSScriptRoot "dispatch_worker.py"

$arguments = @(
    $pythonScript,
    "--task-packet", $TaskPacket,
    "--output", $Output,
    "--repo-root", $RepoRoot,
    "--gemini-bin", $GeminiBinary,
    "--approval-mode", $ApprovalMode,
    "--timeout-seconds", $TimeoutSeconds,
    "--max-repair-attempts", $MaxRepairAttempts,
    "--local-check-timeout-seconds", $LocalCheckTimeoutSeconds
)

if ($Model -ne "") {
    $arguments += @("--model", $Model)
}

if ($DryRun.IsPresent) {
    $arguments += "--dry-run"
}

if ($SkipLocalRequiredChecks.IsPresent) {
    $arguments += "--skip-local-required-checks"
}

python @arguments
exit $LASTEXITCODE

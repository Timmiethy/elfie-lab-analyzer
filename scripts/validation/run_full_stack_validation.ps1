param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$ReadyTimeoutSeconds = 180,
    [switch]$NoStackStart,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ValidationArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe"
}

Push-Location $repoRoot
try {
    if (-not $NoStackStart) {
        Write-Host "Starting required services (db, backend) via docker compose..."
        docker compose up -d db backend | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up failed with exit code $LASTEXITCODE"
        }
    }

    Write-Host "Waiting for backend readiness at $BaseUrl/api/health/ready ..."
    $deadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    $isReady = $false

    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri "$BaseUrl/api/health/ready" -TimeoutSec 5
            $dbReachable = $response.checks.db_reachable
            $artifactWritable = $response.checks.artifact_store_writable
            if ($response.status -eq "ok" -and $dbReachable -eq $true -and $artifactWritable -eq $true) {
                $isReady = $true
                break
            }
            Write-Host "Still waiting: status=$($response.status) db_reachable=$dbReachable artifact_store_writable=$artifactWritable"
        }
        catch {
            Write-Host "Still waiting: ready endpoint unavailable"
        }
        Start-Sleep -Seconds 2
    }

    if (-not $isReady) {
        throw "Backend was not fully ready within $ReadyTimeoutSeconds seconds."
    }

    $runnerArgs = @(
        "scripts/validation/run_backend_corpus_validation.py",
        "--base-url", $BaseUrl,
        "--manifest", "artifacts/validation/pdf_manifest_current.json",
        "--expectations", "scripts/validation/expected_outcomes.example.json",
        "--fail-fast"
    ) + $ValidationArgs

    Write-Host "Running corpus validation with strict readiness checks..."
    & $pythonExe @runnerArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

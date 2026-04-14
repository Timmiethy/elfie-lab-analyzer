<#
.SYNOPSIS
    Run hard ground-truth validation for pdfs_by_difficulty.

.DESCRIPTION
    Executes scripts/run_ground_truth_validation.py and emits a corpus report
    asserting each file against the authoritative ground-truth fixture.

.PARAMETER LoincPath
    Override terminology snapshot directory.

.PARAMETER EnableImageBeta
    Enable image_beta execution for OCR/image PDFs.

.PARAMETER PrintJson
    Print full report JSON to stdout.
#>
[CmdletBinding()]
param(
    [string]$LoincPath = '',
    [switch]$EnableImageBeta,
    [switch]$PrintJson
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$scriptPath = Join-Path $repoRoot 'scripts\run_ground_truth_validation.py'

function Resolve-BackendPython {
    param([string]$Root)

    $venvPython = Join-Path $Root 'backend\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand -and $pythonCommand.Source) {
        return $pythonCommand.Source
    }

    throw "Unable to locate Python runtime. Expected $venvPython or python on PATH."
}

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Ground-truth validation script not found at $scriptPath"
}

$pythonArgs = @($scriptPath)
if (-not [string]::IsNullOrWhiteSpace($LoincPath)) {
    $pythonArgs += @('--loinc-path', $LoincPath)
}
if ($EnableImageBeta) {
    $pythonArgs += '--enable-image-beta'
}
if ($PrintJson) {
    $pythonArgs += '--print-json'
}

Push-Location $repoRoot
try {
    $pythonExe = Resolve-BackendPython -Root $repoRoot
    & $pythonExe @pythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Ground-truth validation exited with code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

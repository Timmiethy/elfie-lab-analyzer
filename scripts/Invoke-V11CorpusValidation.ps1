[CmdletBinding()]
param(
    [string]$LoincPath = '',
    [switch]$EnableImageBeta,
    [switch]$PrintJson
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$scriptPath = Join-Path $repoRoot 'scripts\run_v11_corpus_validation.py'

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Corpus validation script not found at $scriptPath"
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
    & python @pythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Corpus validation exited with code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

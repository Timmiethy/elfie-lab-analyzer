<#
.SYNOPSIS
    Run the v12 manifest-driven corpus validation over pdfs_by_difficulty.

.DESCRIPTION
    Invokes the Python corpus runner which processes every PDF in the manifest
    through the v12 pipeline. Supports both trusted_pdf (PyMuPDF) and image_beta
    (qwen-vl-ocr-2025-11-20) lanes. Parser substrate metadata
    (parser_backend, parser_backend_version, row_assembly_version) is recorded
    in the report for each entry.

    Image-beta lane execution requires:
    - The -EnableImageBeta switch
    - ELFIE_QWEN_OCR_API_KEY environment variable configured

.PARAMETER LoincPath
    Override the terminology snapshot directory.

.PARAMETER EnableImageBeta
    Enable image-beta lane execution for entries with promotion_status=beta_ready.
    Without this switch, image_beta entries are recorded as blocked.

.PARAMETER PrintJson
    Print the full report JSON to stdout after the run.

.EXAMPLE
    & .\scripts\Invoke-V11CorpusValidation.ps1

.EXAMPLE
    & .\scripts\Invoke-V11CorpusValidation.ps1 -EnableImageBeta -PrintJson
#>
[CmdletBinding()]
param(
    [string]$LoincPath = '',
    [switch]$EnableImageBeta,
    [switch]$PrintJson
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$scriptPath = Join-Path $repoRoot 'scripts\run_v11_corpus_validation.py'

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
    $pythonExe = Resolve-BackendPython -Root $repoRoot
    & $pythonExe @pythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Corpus validation exited with code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

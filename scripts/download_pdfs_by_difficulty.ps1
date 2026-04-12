$ErrorActionPreference = 'Stop'

$csvPath = 'D:\apo_documentation\health_report_stress_corpus_100.csv'
$outRoot = 'D:\apo_documentation\pdfs_by_difficulty'

if (-not (Test-Path $csvPath)) {
    throw "CSV not found at $csvPath"
}

New-Item -ItemType Directory -Path $outRoot -Force | Out-Null

$rows = Import-Csv -Path $csvPath | Where-Object { $_.modality -eq 'PDF' }
$results = @()

foreach ($r in $rows) {
    $difficulty = $r.difficulty
    if ([string]::IsNullOrWhiteSpace($difficulty)) {
        $difficulty = 'unknown'
    }
    $difficulty = $difficulty.ToLower()

    $targetDir = Join-Path $outRoot $difficulty
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

    $fileName = $r.file_name
    if ([string]::IsNullOrWhiteSpace($fileName)) {
        $fileName = "id_$($r.id).pdf"
    }
    if (-not $fileName.ToLower().EndsWith('.pdf')) {
        $fileName = ([System.IO.Path]::GetFileNameWithoutExtension($fileName) + '.pdf')
    }

    $url = ($r.source_url -split '\|')[0].Trim()
    $dest = Join-Path $targetDir $fileName

    try {
        Invoke-WebRequest -Uri $url -OutFile $dest -MaximumRedirection 10 -TimeoutSec 120
        $size = (Get-Item $dest).Length
        $results += [pscustomobject]@{
            id = $r.id
            file = $fileName
            difficulty = $difficulty
            status = 'ok'
            bytes = $size
            url = $url
            error = ''
        }
    }
    catch {
        if (Test-Path $dest) {
            Remove-Item $dest -Force -ErrorAction SilentlyContinue
        }
        $results += [pscustomobject]@{
            id = $r.id
            file = $fileName
            difficulty = $difficulty
            status = 'failed'
            bytes = 0
            url = $url
            error = $_.Exception.Message
        }
    }
}

$resultsPath = Join-Path $outRoot 'download_results.json'
$summaryPath = Join-Path $outRoot 'download_summary.txt'

$results | ConvertTo-Json -Depth 5 | Set-Content -Path $resultsPath -Encoding UTF8
($results | Group-Object difficulty, status | Sort-Object Name | Select-Object Name, Count | Out-String) | Set-Content -Path $summaryPath -Encoding UTF8

Write-Output "Output root: $outRoot"
Write-Output "Results: $resultsPath"
Write-Output "Summary: $summaryPath"
Write-Output ''
Write-Output 'Grouped counts:'
$results | Group-Object difficulty, status | Sort-Object Name | Format-Table -AutoSize
Write-Output ''
Write-Output 'Failed downloads:'
$results | Where-Object { $_.status -eq 'failed' } | Select-Object id, file, difficulty, url, error | Format-Table -Wrap -AutoSize

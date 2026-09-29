param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [int]$Threshold = 130,
    [int]$Padding = 8
)

$bundledPython = 'C:\Users\dev\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$scriptPath = Join-Path $PSScriptRoot '..\auto_crop_text.py'

if (-not (Test-Path -LiteralPath $bundledPython)) {
    throw "Bundled Python runtime was not found at: $bundledPython"
}

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Cropper script was not found at: $scriptPath"
}

& $bundledPython $scriptPath `
    --input $InputPath `
    --output-dir $OutputDirectory `
    --threshold $Threshold `
    --padding $Padding

if ($LASTEXITCODE -ne 0) {
    throw "Automatic cropper failed with exit code $LASTEXITCODE"
}

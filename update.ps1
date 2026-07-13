$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$work = Join-Path ([IO.Path]::GetTempPath()) ("anki-deck-update-" + [guid]::NewGuid())
$zip = Join-Path $work "runtime.zip"
$stage = Join-Path $work "runtime"
$asset = "https://github.com/tthin09/anki-deck/releases/latest/download/anki-deck-runtime.zip"

try {
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Write-Host "Downloading the latest version..."
    Invoke-WebRequest -Uri $asset -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force

    foreach ($required in @("run.exe", "migrate.exe", "src\agent-prompt.md", "src\reverse-prompt.md", "vocabulary\template.xlsx")) {
        if (-not (Test-Path (Join-Path $stage $required) -PathType Leaf)) {
            throw "The downloaded package is missing $required."
        }
    }

    foreach ($file in @("run.exe", "migrate.exe", "HUONG-DAN.txt", "KIEM-TRA.cmd")) {
        Copy-Item -LiteralPath (Join-Path $stage $file) -Destination (Join-Path $root $file) -Force
    }
    New-Item -ItemType Directory -Path (Join-Path $root "src"), (Join-Path $root "vocabulary") -Force | Out-Null
    foreach ($file in @("agent-prompt.md", "reverse-prompt.md", "config.example.json")) {
        Copy-Item -LiteralPath (Join-Path $stage "src\$file") -Destination (Join-Path $root "src\$file") -Force
    }
    Copy-Item -LiteralPath (Join-Path $stage "vocabulary\template.xlsx") -Destination (Join-Path $root "vocabulary\template.xlsx") -Force
    Write-Host "Update complete. Your config, input, and generated vocabulary files were preserved."
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if (Test-Path $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
}

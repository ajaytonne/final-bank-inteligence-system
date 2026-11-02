# Installs Tesseract OCR on Windows and tells the app where it is.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File backend\scripts\setup_tesseract_windows.ps1
$exe = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (-not (Test-Path $exe)) {
    Write-Host "Installing Tesseract via winget..."
    winget install --id UB-Mannheim.TesseractOCR -e --accept-package-agreements --accept-source-agreements
}
if (-not (Test-Path $exe)) {
    Write-Host "Install not found at $exe. Download the UB Mannheim installer manually, then set TESSERACT_CMD."
    exit 1
}
setx TESSERACT_CMD $exe | Out-Null          # remembered for new terminals
$env:TESSERACT_CMD = $exe                   # works in this window now
& $exe --version
Write-Host "Done. Close and reopen VS Code terminals, then restart uvicorn."

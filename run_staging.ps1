param(
  [string]$Reviewer = "staging-reviewer",
  [int]$Port = 8876,
  [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Python 3.11 venv not found: $Python" }
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
$Arguments = @("-m", "ocr_inbound", "--environment", "staging", "--reviewer", $Reviewer, "serve", "--host", "127.0.0.1", "--port", "$Port")
if ($NoBrowser) { $Arguments += "--no-browser" }
& $Python @Arguments
exit $LASTEXITCODE

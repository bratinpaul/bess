 @echo off
rem Load one BESS snapshot JSON through the telemetry bulk-load APIs.
rem   load_snapshot.bat "C:\path\to\bess_snapshot.json" [--api http://127.0.0.1:8000] [--out DIR] [--csv-only]
rem Uses the project's .venv; the backend must be running (see load_snapshot.py for details).
setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Python virtual environment not found at "%PY%"
  exit /b 1
)
if "%~1"=="" (
  echo Usage: %~nx0 ^<snapshot.json^> [--api URL] [--out DIR] [--csv-only]
  exit /b 1
)
"%PY%" "%HERE%load_snapshot.py" %*
exit /b %ERRORLEVEL%

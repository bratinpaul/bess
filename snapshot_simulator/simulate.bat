@echo off
rem Snapshot simulator from the command line (same as the Batch -> Simulator page).
rem   simulate.bat --start "2026-09-29 00:00" --end "2026-09-29 23:55" [--seed 7] [--overwrite] [--inbox DIR]
rem   simulate.bat --info
setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Python virtual environment not found at "%PY%"
  exit /b 1
)
"%PY%" "%HERE%simulate.py" %*
exit /b %ERRORLEVEL%

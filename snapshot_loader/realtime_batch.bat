@echo off
rem Run the realtime snapshot batch once, by hand (the scheduled task runs the same script every minute).
rem   realtime_batch.bat [--inbox DIR] [--api URL] [--verbose]
setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Python virtual environment not found at "%PY%"
  exit /b 1
)
"%PY%" "%HERE%realtime_batch.py" %*
exit /b %ERRORLEVEL%

@echo off
rem Load a folder of historical telemetry files for one battery system through the bulk-load APIs.
rem   run_historical_load.bat "historical\Bhadla BESS" EESL-BESS-S02 [more options, see --help]
if "%~2"=="" (
  echo usage: run_historical_load.bat "folder inside input" SYSTEM_NAME [--feeds bms,pcs,...] [--ems-code X] [--hvac-code Y]
  exit /b 2
)
cd /d "%~dp0"
"%~dp0..\.venv\Scripts\python.exe" historical_load.py --folder "%~1" --system "%~2" %3 %4 %5 %6 %7 %8 %9

@echo off
rem Load the master data JSON files in input\static (CSVs -> master-data bulk loaders -> archive -> batchlog).
cd /d "%~dp0"
"%~dp0..\.venv\Scripts\python.exe" static_batch.py -v %*

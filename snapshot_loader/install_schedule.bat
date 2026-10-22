@echo off
rem Schedule the realtime snapshot batch to run every minute (Windows Task Scheduler, current user).
rem Runs with pythonw.exe, so no console window opens. The backend must be running for loads to happen;
rem while it is down the files simply wait in the inbox. Remove with uninstall_schedule.bat.
setlocal
set "HERE=%~dp0"
for %%I in ("%HERE%..\.venv\Scripts\pythonw.exe") do set "PYW=%%~fI"
set "SCRIPT=%HERE%realtime_batch.py"
if not exist "%PYW%" (
  echo pythonw.exe not found at "%PYW%"
  exit /b 1
)
schtasks /Create /TN "BESS\Realtime Snapshot Load" /TR "\"%PYW%\" \"%SCRIPT%\"" /SC MINUTE /MO 1 /F
if errorlevel 1 exit /b 1
rem Windows' defaults would skip every run on battery power; also never overlap runs, and stop a hung run after 10 min
powershell -NoProfile -Command "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10); Set-ScheduledTask -TaskPath '\BESS\' -TaskName 'Realtime Snapshot Load' -Settings $s | Out-Null"
if errorlevel 1 exit /b 1
schtasks /Query /TN "BESS\Realtime Snapshot Load" /FO LIST

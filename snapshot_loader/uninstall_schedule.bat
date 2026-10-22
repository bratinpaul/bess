@echo off
rem Stop the every-minute realtime snapshot batch (removes the scheduled task).
schtasks /Delete /TN "BESS\Realtime Snapshot Load" /F

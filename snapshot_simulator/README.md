# Snapshot simulator

Writes one plant snapshot file per 5 minutes, from a start to an end time, in the `bess_snapshot.json` format,
into the realtime inbox `input\realtime\YYYY-MM-DD-HH-MM-SS.json`. The every-minute realtime batch
(`snapshot_loader\realtime_batch.py`) then loads them through the seven bulk-load APIs.

| File | What it is |
|---|---|
| `simulator.py` | The generator: sampling, snapshot building, file writing (needs a SQLAlchemy session) |
| `simulate.py` / `simulate.bat` | Command line runner |
| `__init__.py` | Package exports (`simulate`, `source_info`, `SimulatorError`, `INBOX`, `MAX_FILES`) |

Other places that use it (they stay in their apps):
- **API**: `backend/app/routers/batch.py` → `GET /api/batch/simulator/info`, `POST /api/batch/simulator/run`
  (imports this package from the project root)
- **Page**: `frontend/src/app/features/batch/snapshot-simulator/` → left navigation **Batch → Simulator**

## Run it

From the page: enter start and end, click **Generate files**. From the command line:

```
snapshot_simulator\simulate.bat --info
snapshot_simulator\simulate.bat --start "2026-09-29 00:00" --end "2026-09-29 23:55" --seed 7
snapshot_simulator\simulate.bat --start "2026-09-29 00:00" --end "2026-09-29 00:55" --inbox D:\scratch
```

Options: `--seed` (same seed + range = same files), `--overwrite` (replace same-named files still waiting in
the inbox), `--source-from` / `--source-to` (historical days to sample), `--inbox` (write elsewhere, e.g. to try
it without the batch loading the files). At most 7 days (2016 files) per run; times are plant local time.

## How values are sampled

- Each simulated day replays one historical day with complete BMS, PCS, EMS and HVAC telemetry, picked at
  random among the 3 whose SOC at that time is closest to the previous interval's (the last stored or simulated
  value) - so the state carries on across joins. Every file takes all feeds from the same source moment.
- Module values come from the same day, or from a day that has module data, at the same time of day.
- The dispatch running and the alarms active at the source moment are moved to the simulated day (windows
  clipped to it). Where a dispatch is already stored, the file carries none; simulated windows are fitted
  around stored ones, so the dispatch load never rejects them.
- BMS cumulative counters (charge / discharge kWh, equivalent full cycles) continue from the last stored value
  by the source day's increments.
- System, PCS, EMS, HVAC, pack and module codes and the config block come from master data.
- Files are written under a temporary name and renamed, so the batch never reads a half-written file.

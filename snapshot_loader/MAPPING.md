# snapshot_loader - files

| File | What it is |
|---|---|
| `load_snapshot.py` / `.bat` | One snapshot JSON → seven CSVs → seven bulk-load APIs (the mapping below) |
| `realtime_batch.py` / `.bat` | The every-minute batch over the realtime inbox (below) |
| `batch_control.py` | Inbox, lock, schedule, run-now and `battery_raw.batchlog` queries - used by the backend API `/api/batch/realtime` (Batch → Realtime Load page) |
| `install_schedule.bat` / `uninstall_schedule.bat` | Add / remove the Windows scheduled task |
| `logs/`, `output/` | Batch log file; CSVs of manual `load_snapshot` runs |

The backend router `backend/app/routers/batch.py` only exposes these (and the simulator in
`<project>/snapshot_simulator`) over HTTP; the page is `frontend/src/app/features/batch/`.

# Realtime batch (every minute)

`realtime_batch.py` is scheduled every minute (Task Scheduler task **BESS\Realtime Snapshot Load**,
installed by `install_schedule.bat`, removed by `uninstall_schedule.bat`; run once by hand with
`realtime_batch.bat`). Each run:

1. picks up every `C:\bratin\claude\bess\input\realtime\YYYY-MM-DD-HH-MM-SS.json` and loads them one after
   another, sorted by the date/time in the name, **oldest first** (other names are ignored; files changed in
   the last 5 s wait for the next run; at most 500 files per run - a bigger backlog continues next minute,
   still oldest first);
2. writes the seven CSVs to `input\realtime\archieve\<YYYY-MM-DD-HH-MM-SS>\` and loads each through its
   bulk-load API (the mapping below);
3. writes `load_report.json` there and moves the input file there;
4. inserts one row into **`battery_raw.batchlog`**: status SUCCESS / PARTIAL / FAILED, timings, row totals,
   per-feed results, warnings, reassigned IDs, error, archive path and the full report.

A file that can't be used is archived with status FAILED (not retried). If the backend is down nothing moves
and the next run retries. A lock file prevents overlapping runs. Log: `logs\realtime_batch.log`.

```sql
SELECT batch_id, file_name, status, rows_inserted, rows_updated, rows_skipped, error_message
FROM battery_raw.batchlog ORDER BY batch_id DESC LIMIT 20;
```

# Snapshot simulator

Code in the `snapshot_simulator` folder at the project root (see its README); run from the frontend
**Batch → Simulator** (API `POST /api/batch/simulator/run`) or `snapshot_simulator\simulate.bat`. It writes one snapshot file per 5 minutes from a start to an end
time (at most 7 days per run) into `input\realtime\YYYY-MM-DD-HH-MM-SS.json`, in the bess_snapshot.json
format; the realtime batch then loads them.

- Values are sampled from stored telemetry: each simulated day replays one historical day that has complete
  BMS, PCS, EMS and HVAC data (picked at random among the 3 whose SOC at that time is closest to the previous
  interval's, so the state carries on). All feeds of a file come from the same source moment; modules come from
  a day with module data at the same time of day.
- The dispatch running and the alarms active at the source moment are moved to the simulated day (windows
  clipped to that day). Where a dispatch is already stored, the snapshot carries none and simulated windows
  are fitted around stored ones, so dispatch loads don't collide.
- BMS cumulative counters continue from the last stored value by the source day's increments.
- Codes come from master data (system, PCS, EMS, HVAC, pack and module serials), so they load unchanged.
- Optional: a sample period (source days), a seed (same seed + range = same files), and replacing files of
  the same name still waiting in the inbox. Files are written under a temporary name and renamed, so the
  batch never picks up a half-written file.

# Snapshot → CSV → bulk-load API mapping

`load_snapshot.py` turns one plant snapshot (`bess_snapshot.json`, one 5-minute interval) into seven CSV
files and posts each to its bulk-load API. The table in the script (`FEEDS`) is the source of truth; this
page describes it.

```
load_snapshot.bat "C:\bratin\claude\bess\BESS DESIGN\bess_snapshot.json"
load_snapshot.bat snapshot.json --csv-only          # write the CSVs, don't load
load_snapshot.bat snapshot.json --api http://host:8000 --out D:\loads\run1
```

CSVs go to `output/<YYYYMMDD_HHMM>/` with a `load_report.json`. Exit code 0 = all loaded,
1 = snapshot/file problem (nothing loaded), 2 = rows skipped or a load failed.

**Timestamps**: `meta.timestamp` is the interval time for every telemetry row. It is plant local time
(Asia/Kolkata), sent without a zone and stored as given — no UTC conversion.
**Insert or update**: every bulk load checks the primary key - asset + timestamp for BMS, module, PCS, EMS
and HVAC telemetry; alarm/dispatch id + start for alarms and dispatches. A new key is inserted; an existing one
is **updated, only in the columns the file has** - the other columns keep their stored values (e.g. a
dispatch's revenue, or a PCS energy counter the snapshot doesn't carry). A key repeated inside one file counts
once (the last row wins). So loading the same snapshot again never duplicates data.

**Alarm / dispatch IDs**: before writing the CSVs the loader asks the API about each ID. If the database
already uses that ID for a different start time, the event is treated as new and gets the next free ID
(e.g. DSP-00022 → DSP-00358); the original ID goes in the dispatch's `note` and in `load_report.json`
(alarms have no note column). If this loader already stored the event (same EMS + start for a dispatch;
same alarm code, source + start for an alarm), that record's ID is reused, so re-runs don't duplicate it.

**Running dispatch**: one EMS runs one dispatch at a time. A dispatch that starts after the EMS's running
dispatch (no end time) ends it: the dispatch API closes the running one at the new start (status Completed)
and reports it (`closed_dispatches`); any other overlap is still rejected.

## BMS → `bms_telemetry.csv` → `POST /api/system-telemetry/bulk`
1 row. Paths are under `site.bess_system.bms.system` unless shown.

| CSV column | Snapshot |
|---|---|
| system_name | `site.bess_system.system_code` (must equal the battery system's name, e.g. 01-BATTERY-01) |
| timestamp | `meta.timestamp` |
| mode | `mode` |
| soc_% / soh_% | `soc_pct` / `soh_pct` |
| pack_voltage_v, pack_current_a, power_kw, c_rate | same names |
| cell_v_avg_v / min / max / cell_v_delta_mv | `cell_voltage.avg_v` / `min_v` / `max_v` / `delta_mv` |
| cell_temp_avg_c / min / max | `cell_temperature.avg_c` / `min_c` / `max_c` |
| coolant_temp_c, ambient_temp_c, insulation_res_kohm | same names |
| cum_charge_kwh / cum_discharge_kwh / equiv_full_cycles | `cumulative.charge_kwh` / `discharge_kwh` / `equiv_full_cycles` |
| contactor_status | `contactor_state` |
| alarm_level | `alarm_level` |

Not in the snapshot (stored empty): avail_charge_kw, avail_discharge_kw. `alarm_flags` has no BMS column.

## Modules → `module_telemetry.csv` → `POST /api/module-telemetry/bulk`
One row per module in `site.bess_system.bms.packs[].modules[]` (16).

| CSV column | Snapshot (per module) |
|---|---|
| module_code | `module_code` (MOD-07 → the battery module numbered 7) |
| ts | `meta.timestamp` |
| cell_v_avg_v / min / max | `cell_voltage.avg_v` / `min_v` / `max_v` |
| cell_temp_max_c / cell_temp_min_c | `cell_temperature.max_c` / `min_c` |
| imbalance_mv | `cell_voltage.imbalance_mv` (checked against max − min) |
| balancing_active | `balancing_active` |

## PCS → `pcs_telemetry.csv` → `POST /api/pcs-telemetry/bulk`
1 row from `site.bess_system.pcs`.

| CSV column | Snapshot |
|---|---|
| pcs_code | `pcs_code` (must equal the PCS code, e.g. 01-01-PCS-01) |
| ts | `meta.timestamp` |
| mode_code, grid_service | `mode`, `grid_service` |
| ac_active_power_kw / ac_reactive_power_kvar / ac_apparent_power_kva | `ac.active_power_kw` / `reactive_power_kvar` / `apparent_power_kva` |
| power_factor, ac_frequency_hz | `ac.power_factor`, `ac.frequency_hz` |
| ac_voltage_ab_v / bc / ca | `ac.voltage_ll_v.ab` / `bc` / `ca` |
| ac_current_a_a / b / c | `ac.current_a.a` / `b` / `c` |
| thd_voltage_pct / thd_current_pct | `ac.thd_pct.voltage` / `current` |
| dc_voltage_v / dc_current_a / dc_power_kw | `dc.voltage_v` / `current_a` / `power_kw` |
| efficiency_pct | `efficiency_pct` |
| igbt_temp_c / heatsink_temp_c / inlet_coolant_temp_c | `thermal.igbt_c` / `heatsink_c` / `inlet_coolant_c` |
| breaker_state, alarm_level | same names |

Not in the snapshot: ambient_temp_c, avail_charge_kw, avail_discharge_kw, ac_energy_import_kwh, ac_energy_export_kwh.

## EMS → `ems_telemetry.csv` → `POST /api/ems-telemetry/bulk` (form field `ems_code` = `site.ems.ems_code`)
1 row from `site.ems`.

| CSV column | Snapshot |
|---|---|
| ts | `meta.timestamp` |
| dispatch_mode, grid_service, market_price_mwh | same names |
| p_setpoint_kw / tracking_error_kw / agc_signal | `setpoint.p_setpoint_kw` / `tracking_error_kw` / `agc_signal` |
| poi_active_power_kw / poi_reactive_power_kvar / poi_voltage_kv | `poi.active_power_kw` / `reactive_power_kvar` / `voltage_kv` |
| grid_frequency_hz | `poi.frequency_hz` |
| plant_soc_pct / target_soc_pct | `soc.plant_soc_pct` / `target_soc_pct` |
| avail_charge_kw / avail_discharge_kw / plant_available | `availability.*` |
| aux_load_kw, alarm_level | same names |

Not in the snapshot: avail_charge_energy_kwh, avail_discharge_energy_kwh, aux_load_pct, cum_import_kwh,
cum_export_kwh, revenue_cum_usd, units_online.

## HVAC → `hvac_telemetry.csv` → `POST /api/hvac-telemetry/bulk` (form field `hvac_code` = `site.bess_system.hvac.hvac_code`)
1 row from `site.bess_system.hvac`.

| CSV column | Snapshot |
|---|---|
| ts | `meta.timestamp` |
| cooling_mode | `cooling_mode` |
| coolant_setpoint_c / supply_temp_c / return_temp_c / delta_t_c / flow_lpm | `coolant.setpoint_c` / `supply_c` / `return_c` / `delta_t_c` / `flow_lpm` |
| compressor_speed_pct, condenser_fan_pct, refrig_suction_bar, refrig_discharge_bar | `mechanical.*` |
| battery_heat_load_kw, cooling_capacity_kw, heat_rejected_kw, cop | `thermal_balance.*` |
| hvac_power_kw | `hvac_power_kw` |
| enclosure_temp_c / enclosure_humidity_pct | `enclosure.temp_c` / `humidity_pct` |
| alarm_level, alarm_flags | same names |

Not in the snapshot: ambient_temp_c, filter_dp_pa, cum_energy_kwh, compressor_runtime_h, units_running.

## Dispatch events → `dispatch_events.csv` → `POST /api/dispatch-events/bulk`
1 row from `site.active_dispatch` (none when it is absent).

| CSV column | Snapshot |
|---|---|
| dispatch_id, command_code, dispatch_mode, grid_service, source | same names |
| ems_code | `site.ems.ems_code` |
| issued_at, effective_from, effective_to | same names |
| p_setpoint_kw, target_soc_pct, ramp_rate_kw_s, status | same names |

Not in the snapshot: soc_start_pct, soc_end_pct, import_kwh, export_kwh, avg_price_mwh, revenue_usd,
accepted, note — kept as stored for an existing dispatch; empty (energy 0, accepted true) for a new one.

## Alarms → `alarm_events.csv` → `POST /api/alarm-events/bulk`
One row per item in `site.active_alarms[]` (none when empty).

| CSV column | Snapshot |
|---|---|
| alarm_id, source_system, asset_type, asset_code, alarm_code | same names (asset linked to master data) |
| severity, severity_level | same names |
| start_time, end_time, trigger_value, threshold_value, unit, status | same names |

alarm_type, description and probable_cause come from the alarm catalog, so they aren't sent.
Not in the snapshot: acknowledged_by, acknowledged_at — kept as stored for an existing alarm.

## Checks before loading
- required sections and codes present; `meta.timestamp` is ISO, without a time zone, on the interval boundary
- each pack's `module_count` matches the modules listed
- the same measurement agrees across systems: BMS power vs PCS DC power, BMS SOC vs EMS plant SOC,
  BMS pack voltage vs PCS DC voltage (warnings)
- a dispatch or alarm dated more than a day from the snapshot time (warning)
- each API then validates its rows (codes must exist in master data, ranges, times) and reports skipped rows

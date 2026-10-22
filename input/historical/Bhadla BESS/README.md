# Bhadla BESS Site — historical telemetry, 1 Aug – 30 Sep 2026

Generated from the seven sample files in `input\historical` by `historical_generator\generate_bhadla.py`. The run is seeded, so re-running it gives the same files.

The data is for Bhadla BESS Site (Tata Power Renewable Energy Limited). It is labelled with that site's master data:
- battery system `EESL-BESS-S02`
- PCS `EESL-BESS-S02-PCS-01`
- EMS `EESL-BESS-S02-EMS-01`
- HVAC `EESL-BESS-S02-HVAC-01`
- packs `CONT-S02-01-PACK-01…06`
- modules `EESL-S02-P01-M01…P06-M16`

`historical_generator\validate_bhadla.py` parses every file with the backend's own importers (a dry run that writes nothing) and checks the data.

## Files

| File | Rows | Load with |
|------|------|-----------|
| `BESS_BMS_Bhadla_…_5min.xlsx` | 17,568 (61 days × 288) | Telemetry → BMS upload / `POST /api/system-telemetry/bulk` (column `System_Name`) |
| `BESS_PCS_Bhadla_…_5min.xlsx` | 17,568 | Telemetry → PCS / `POST /api/pcs-telemetry/bulk` (column `pcs_code`) |
| `BESS_EMS_Bhadla_…__EESL-BESS-S02-EMS-01.xlsx` | 17,568 | Telemetry → EMS, choose EMS `EESL-BESS-S02-EMS-01` (form field `ems_code`) |
| `BESS_HVAC_Bhadla_…__EESL-BESS-S02-HVAC-01.xlsx` | 17,568 | Telemetry → HVAC, choose `EESL-BESS-S02-HVAC-01` (form field `hvac_code`) |
| `module\BESS_ModuleTelemetry_Bhadla_<date>.csv` | 30 files × 27,648 (96 modules × 288), 1–30 Sep | Telemetry → Module / `POST /api/module-telemetry/bulk`, one file per upload |
| `BESS_Alarm_Bhadla_2026-08-01_2026-09-30.xlsx` | ~180 alarms | Telemetry → Alarms / `POST /api/alarm-events/bulk` |
| `BESS_DispatchEvents_Bhadla_2026-08-01_2026-09-30.xlsx` | ~715 dispatches | Telemetry → Dispatch Events / `POST /api/dispatch-events/bulk` |
| `scenario_calendar.csv` | 61 | The day plan: source sample day, scenario, dispatch scale, offline window |

IDs are prefixed `BHD-ALM-` and `BHD-DSP-`, so they never collide with the Kolkata site's alarms and dispatches. All loaders update rows that already exist, so loading a file twice is safe.

**Load order:** load the master data first (already done by the static data load). Then load BMS, PCS, EMS, HVAC and module telemetry in any order, then alarms and dispatch events.

## How the data was made

**Sampling.** Each day copies one sample day, and all feeds of that day come from the same sample day, so they stay consistent with each other.
- Each month first gets a set of sample days that covers every scenario seen in the samples: frequency regulation, VOLT_VAR and FREQ_WATT, BMS comm warning, low insulation, compressor fault, a PCS alarm, and all 21 alarm codes.
- The remaining days are drawn at random without repeats.
- 1 Aug keeps the sample's own first day, which starts at 55 % SOC.

**Scaling to Bhadla's ratings** (1.5 MW / 3,440.6 kWh, 1,664 cells in series, 33 kV):

| Quantity | How it was scaled |
|---|---|
| Power | × 1.5 |
| SOC swing | × 0.872, because the battery is larger |
| Pack voltage | cell voltage × 1,664 |
| Current | P / V |
| PCS DC voltage | the BMS pack voltage |
| PCS AC voltage | 33 kV; currents computed from kVA / V |
| Aux load | × 1.5, plus the extra HVAC power on hot days |
| Available energy | from SOC between 10 % and 95 % |
| Cumulative counters, equivalent cycles, revenue | recomputed over the 61 days, starting at 0 on 1 Aug like the samples |
| Plant ambient | 3 °C above the sample site |

**SOH** starts at 99.30 %, the average of the S02 modules. It falls with cycling (heat days age 1.6 × faster) and with calendar time, never rises, and ends at about 99.03 %.

**Modules (September).** Each of the 96 modules has its own voltage offset, temperature offset and spread, drawn from the 16 sample modules, plus a pack-to-pack temperature gradient. Modules with a lower master-data SOH show more imbalance. Balancing runs mostly while charging, as in the sample. The BMS cell min/max voltage and temperature for September are the envelope of the modules.

## Scenarios

| Scenario | Days | What happens |
|---|---|---|
| Sample mix | all | Arbitrage, scheduled charge, frequency regulation, VOLT_VAR/FREQ_WATT, comm faults, SOC limits, overloads, CompressorFault, LowInsulation … in both months |
| Desert heat | 27–28 Aug, 9–11, 18, 24–25 Sep | Afternoon ambient 42–45 °C. Cells reach about 42 °C, and power and availability are derated to 80 %. Free cooling switches to the compressor, HVAC power and aux load rise, and COP drops. **HighCellTemp**, **HighCoolantTemp** and **IGBT_OVERTEMP** alarms fire where the values cross the limits (40 / 36 / 60 °C) |
| Monsoon / low price | 7–8, 14, 22–23 Aug, 4 Sep | Cooler, enclosure humidity +22 %. Prices are compressed to a low spread and cycling is shallow (35 %). **HighHumidity** alarms. On 8 Aug the DC insulation dips below 2,100 kΩ (**LowInsulation**, critical) |
| Planned maintenance | 19 Aug, 07:00–17:00 | Contactors open, PCS IDLE with breaker OPEN, EMS IDLE, units_online 0, plant unavailable. Dispatch events: standby → maintenance (IDLE) → back in service |
| Forced outage | 15 Sep, 09:00–16:30 | **GROUND_FAULT** trips the PCS (mode FAULT, breaker TRIPPED, alarm level 3). The EMS reports **DISPATCH_REJECTED** and SOC is held. The plant restarts before the evening discharge |

The exact day list is in `scenario_calendar.csv`.

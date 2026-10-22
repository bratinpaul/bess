# Bhuj BESS Site — generated historical telemetry, 2026-09-01 – 2026-09-30

Generated 2026-10-01T22:53:17+05:30 by Batch → Historical Generator (`historical_generator/generator.py`) from the sample files in `input\historical`. Battery system `EESL-BESS-S01`; climate profile: hot arid (Kutch); alarm / dispatch ids `BHU-ALM-` / `BHU-DSP-`.

| Feed | Files | Rows |
|---|---|---|
| BMS | 1 | 8,640 |
| PCS | 1 | 8,640 |
| EMS | 1 | 8,640 |
| HVAC | 1 | 8,640 |
| Alarms | 1 | 81 |
| Dispatch events | 1 | 356 |
| Module | 30 | 829,440 |

Scenario days:

- 2026-09-11 maintenance: planned maintenance 07:00-17:00: contactors and PCS breaker open, plant unavailable
- 2026-09-15 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %); moisture: DC insulation below 2100 kOhm for ~45 min
- 2026-09-20 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %)
- 2026-09-21 outage: forced outage: PCS ground fault trips the breaker at 09:00, restart 16:30; SOC held while offline
- 2026-09-25 heat: heat wave: afternoon ambient +8.9 degC over the sample site, power derated to 80 %
- 2026-09-26 heat: heat wave: afternoon ambient +10.8 degC over the sample site, power derated to 80 %
- 2026-09-27 heat: heat wave: afternoon ambient +8.4 degC over the sample site, power derated to 80 %

Load them with Batch → Historical Load (folder `historical\Bhuj BESS`, system `EESL-BESS-S01`).

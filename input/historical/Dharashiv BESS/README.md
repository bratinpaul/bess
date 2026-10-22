# Dharashiv BESS Site — generated historical telemetry, 2026-09-01 – 2026-09-30

Generated 2026-10-01T22:53:53+05:30 by Batch → Historical Generator (`historical_generator/generator.py`) from the sample files in `input\historical`. Battery system `EESL-BESS-S05`; climate profile: semi-arid plateau (Marathwada); alarm / dispatch ids `DHA-ALM-` / `DHA-DSP-`.

| Feed | Files | Rows |
|---|---|---|
| BMS | 1 | 8,640 |
| PCS | 1 | 8,640 |
| EMS | 1 | 8,640 |
| HVAC | 1 | 8,640 |
| Alarms | 1 | 89 |
| Dispatch events | 1 | 344 |
| Module | 30 | 829,440 |

Scenario days:

- 2026-09-11 maintenance: planned maintenance 07:00-17:00: contactors and PCS breaker open, plant unavailable
- 2026-09-16 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %); moisture: DC insulation below 2100 kOhm for ~45 min
- 2026-09-17 heat: heat wave: afternoon ambient +7.1 degC over the sample site, power derated to 80 %
- 2026-09-18 heat: heat wave: afternoon ambient +5.3 degC over the sample site, power derated to 80 %
- 2026-09-19 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %)
- 2026-09-20 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %)
- 2026-09-21 outage: forced outage: PCS ground fault trips the breaker at 09:00, restart 16:30; SOC held while offline
- 2026-09-26 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %)
- 2026-09-27 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %)
- 2026-09-28 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %)

Load them with Batch → Historical Load (folder `historical\Dharashiv BESS`, system `EESL-BESS-S05`).

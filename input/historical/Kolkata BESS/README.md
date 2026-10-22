# Kolkata Grid Storage Site — generated historical telemetry, 2026-09-01 – 2026-09-30

Generated 2026-10-01T22:54:22+05:30 by Batch → Historical Generator (`historical_generator/generator.py`) from the sample files in `input\historical`. Battery system `01-BATTERY-01`; climate profile: moderate; alarm / dispatch ids `KOL-ALM-` / `KOL-DSP-`.

| Feed | Files | Rows |
|---|---|---|
| BMS | 1 | 8,640 |
| PCS | 1 | 8,640 |
| EMS | 1 | 8,640 |
| HVAC | 1 | 8,640 |
| Alarms | 1 | 81 |
| Dispatch events | 1 | 350 |
| Module | 30 | 138,240 |

Scenario days:

- 2026-09-02 heat: heat wave: afternoon ambient +6.0 degC over the sample site, power derated to 80 %
- 2026-09-03 heat: heat wave: afternoon ambient +5.2 degC over the sample site, power derated to 80 %
- 2026-09-11 maintenance: planned maintenance 07:00-17:00: contactors and PCS breaker open, plant unavailable
- 2026-09-15 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %); moisture: DC insulation below 2100 kOhm for ~45 min
- 2026-09-16 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %)
- 2026-09-21 outage: forced outage: PCS ground fault trips the breaker at 09:00, restart 16:30; SOC held while offline
- 2026-09-28 monsoon: monsoon: cool, humid, compressed low prices, shallow cycling (35 %)

Load them with Batch → Historical Load (folder `historical\Kolkata BESS`, system `01-BATTERY-01`).

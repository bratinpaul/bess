"""Check the generated Bhadla files: parse each with the backend's own importers (read-only - nothing is written
to the database) and check the data: continuity, counters, ratings, scenario coverage per month.

Run: .venv\\Scripts\\python historical_generator\\validate_bhadla.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "input" / "historical" / "Bhadla BESS"
sys.path.insert(0, str(PROJECT / "backend"))

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services import (  # noqa: E402
    alarm_event_import, dispatch_event_import, ems_telemetry_import, hvac_telemetry_import, module_telemetry_import,
    pcs_telemetry_import, telemetry_import,
)

problems: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + message)
    if not ok:
        problems.append(message)


def parse_all() -> None:
    print("importers (dry run)")
    tag = "Bhadla_2026-08-01_2026-09-30_5min"
    with SessionLocal() as db:
        ems_id = db.query(models.EmsController.ems_id).filter_by(ems_code="EESL-BESS-S02-EMS-01").scalar()
        hvac_id = db.query(models.HvacUnit.hvac_id).filter_by(hvac_code="EESL-BESS-S02-HVAC-01").scalar()
        jobs = [
            ("BMS", f"BESS_BMS_{tag}.xlsx", lambda n, c: telemetry_import.parse_telemetry_file(n, c, db)),
            ("PCS", f"BESS_PCS_{tag}.xlsx", lambda n, c: pcs_telemetry_import.parse_pcs_telemetry_file(n, c, db)),
            ("EMS", f"BESS_EMS_{tag}__EESL-BESS-S02-EMS-01.xlsx",
             lambda n, c: ems_telemetry_import.parse_ems_telemetry_file(n, c, db, ems_id)),
            ("HVAC", f"BESS_HVAC_{tag}__EESL-BESS-S02-HVAC-01.xlsx",
             lambda n, c: hvac_telemetry_import.parse_hvac_telemetry_file(n, c, db, hvac_id)),
        ]
        for label, name, fn in jobs:
            valid, errors, total = fn(name, (OUT / name).read_bytes())
            check(not errors and len(valid) == total, f"{label}: {len(valid)}/{total} rows valid"
                  + (f" - first error: {errors[0]}" if errors else ""))
        bad = 0
        files = sorted((OUT / "module").glob("*.csv"))
        for f in files:
            valid, errors, total = module_telemetry_import.parse_module_telemetry_file(f.name, f.read_bytes(), db)
            bad += len(errors)
            if errors and bad == len(errors):
                print("    first module error:", f.name, errors[0])
        check(bad == 0, f"Module: {len(files)} daily files, {bad} row errors")
        name = "BESS_Alarm_Bhadla_2026-08-01_2026-09-30.xlsx"
        _, rows, errors, total, ignored, linked, _ = alarm_event_import.parse_alarm_event_file(name, (OUT / name).read_bytes(), db)
        check(not errors and len(rows) == total, f"Alarms: {len(rows)}/{total} valid, {linked} linked to master data"
              + (f" - first error: {errors[0]}" if errors else ""))
        check(linked == total, "every alarm asset matched to a Bhadla master record")
        name = "BESS_DispatchEvents_Bhadla_2026-08-01_2026-09-30.xlsx"
        _, kept, errors, total, *_ = dispatch_event_import.parse_dispatch_event_file(name, (OUT / name).read_bytes(), db)
        check(not errors and len(kept) == total, f"Dispatch events: {len(kept)}/{total} valid"
              + (f" - first error: {errors[0]}" if errors else ""))


def data_checks() -> None:
    print("data")
    tag = "Bhadla_2026-08-01_2026-09-30_5min"
    bms = pd.read_excel(OUT / f"BESS_BMS_{tag}.xlsx")
    pcs = pd.read_excel(OUT / f"BESS_PCS_{tag}.xlsx")
    ems = pd.read_excel(OUT / f"BESS_EMS_{tag}__EESL-BESS-S02-EMS-01.xlsx")
    hvac = pd.read_excel(OUT / f"BESS_HVAC_{tag}__EESL-BESS-S02-HVAC-01.xlsx")
    ts = bms.Timestamp
    check(ts.iloc[0] == pd.Timestamp("2026-08-01") and ts.iloc[-1] == pd.Timestamp("2026-09-30 23:55")
          and (ts.diff().dropna() == pd.Timedelta("5min")).all(), "BMS covers 1 Aug 00:00 - 30 Sep 23:55 every 5 min")
    jumps = bms["SOC_%"].diff().abs()
    check(jumps.max() < 6, f"SOC continuous (largest 5-min change {jumps.max():.2f} %)")
    check(bms["SOC_%"].between(5, 100).all(), f"SOC {bms['SOC_%'].min():.1f}-{bms['SOC_%'].max():.1f} %")
    check(bms.Power_kW.abs().max() <= 1500 * 1.02, f"|power| <= 1.5 MW (max {bms.Power_kW.abs().max():.0f} kW)")
    check((bms["SOH_%"].diff().dropna() <= 0).all(), f"SOH never rises ({bms['SOH_%'].iloc[0]} -> {bms['SOH_%'].iloc[-1]})")
    for c in ("Cum_Charge_kWh", "Cum_Discharge_kWh", "Equiv_Full_Cycles"):
        check((bms[c].diff().dropna() >= 0).all(), f"{c} never decreases (end {bms[c].iloc[-1]})")
    pv = bms.Pack_Voltage_V
    check(pv.between(1664 * 2.9, 1664 * 3.65).all(), f"pack voltage {pv.min():.0f}-{pv.max():.0f} V (1664 cells)")
    check((pcs.dc_voltage_v == pv).all(), "PCS DC voltage = BMS pack voltage")
    check(ems.cum_import_kwh.is_monotonic_increasing and ems.cum_export_kwh.is_monotonic_increasing, "EMS counters rise")
    check(hvac.cum_energy_kwh.is_monotonic_increasing, "HVAC energy counter rises")
    check(bms.Cell_Temp_Max_C.max() > 40, f"heat days reach {bms.Cell_Temp_Max_C.max():.1f} degC cell max")

    print("scenario coverage per month")
    alarms = pd.read_excel(OUT / "BESS_Alarm_Bhadla_2026-08-01_2026-09-30.xlsx")
    alarms["month"] = pd.to_datetime(alarms.start_time).dt.month
    for name, series in [
        ("EMS dispatch mode", ems.assign(m=ems.ts.dt.month).groupby("m").dispatch_mode.apply(set)),
        ("EMS grid service", ems.assign(m=ems.ts.dt.month).groupby("m").grid_service.apply(set)),
        ("PCS grid service", pcs.assign(m=pcs.ts.dt.month).groupby("m").grid_service.apply(set)),
        ("PCS mode", pcs.assign(m=pcs.ts.dt.month).groupby("m").mode_code.apply(set)),
        ("PCS breaker", pcs.assign(m=pcs.ts.dt.month).groupby("m").breaker_state.apply(set)),
        ("BMS flags", bms.assign(m=bms.Timestamp.dt.month).groupby("m").Alarm_Flags.apply(set)),
        ("HVAC flags", hvac.assign(m=hvac.ts.dt.month).groupby("m").alarm_flags.apply(set)),
        ("HVAC mode", hvac.assign(m=hvac.ts.dt.month).groupby("m").cooling_mode.apply(set)),
        ("alarm codes", alarms.groupby("month").alarm_code.apply(set)),
    ]:
        print(f"  {name:18} Aug: {sorted(series[8])}")
        print(f"  {'':18} Sep: {sorted(series[9])}")
    sample = pd.read_excel(PROJECT / "input" / "historical" / "BESS_Alarm_SampleData.xlsx")
    for m in (8, 9):
        missing = set(sample.alarm_code) - set(alarms[alarms.month == m].alarm_code)
        check(not missing, f"month {m}: every sample alarm code present" + (f" (missing {sorted(missing)})" if missing else ""))


if __name__ == "__main__":
    parse_all()
    data_checks()
    print(f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)

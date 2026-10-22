"""Run a KPI calculation from the command line (e.g. a scheduled task), from the backend folder:

    ..\.venv\Scripts\python.exe -m app.services.bms_kpi.cli                         # BMS: all systems, all days
    ..\.venv\Scripts\python.exe -m app.services.bms_kpi.cli --system 1 --start 2026-09-01 --end 2026-09-30
    ..\.venv\Scripts\python.exe -m app.services.bms_kpi.cli --domain pcs --system 6  # PCS unit 6 (pcs_id)
    ..\.venv\Scripts\python.exe -m app.services.bms_kpi.cli --dry-run               # compute + count, store nothing
"""
import argparse
import json
from datetime import date

from app.database import SessionLocal
from app.services.bms_kpi.calculator import run
from app.services.bms_kpi.config import load_config
from app.services.bms_kpi.domain import DOMAINS


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate the KPIs defined in kpi_config/<domain>_kpi.yaml")
    parser.add_argument("--domain", choices=sorted(DOMAINS), default="bms", help="bms (default), pcs or ems")
    parser.add_argument("--system", type=int, action="append",
                        help="entity id: battery_system_id (bms), pcs_id (pcs) or ems_id (ems); repeatable, default all")
    parser.add_argument("--start", type=date.fromisoformat, help="first day, YYYY-MM-DD (plant-local)")
    parser.add_argument("--end", type=date.fromisoformat, help="last day, YYYY-MM-DD (inclusive)")
    parser.add_argument("--dry-run", action="store_true", help="compute and report, roll back")
    args = parser.parse_args()
    if args.start and args.end and args.start > args.end:
        parser.error("--start must be on or before --end")

    domain = DOMAINS[args.domain]
    cfg = load_config(domain)
    db = SessionLocal()
    try:
        result = run(db, cfg, triggered_by="cli", system_ids=args.system, start_date=args.start,
                     end_date=args.end, dry_run=args.dry_run, domain=domain)
    finally:
        db.close()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

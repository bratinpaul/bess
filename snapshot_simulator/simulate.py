"""Run the snapshot simulator from the command line (the frontend page Batch -> Simulator does the same).

    python simulate.py --start "2026-09-29 00:00" --end "2026-09-29 23:55" [--seed 7] [--overwrite]
                       [--source-from 2026-08-01] [--source-to 2026-08-30] [--inbox DIR]
    python simulate.py --info

Times are plant local time. Files go to the realtime inbox (default input/realtime), where the every-minute
realtime batch loads them. Exit code 0 = files written, 1 = bad input or nothing to sample from.
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # so the snapshot_simulator package imports when run as a script

from snapshot_simulator.simulator import INBOX, SimulatorError, simulate, source_info  # noqa: E402

PLANT_TZ = "Asia/Kolkata"


def session():
    """A session on the database the backend uses (DATABASE_URL in backend/.env), in plant local time."""
    env = HERE.parent / "backend" / ".env"
    url = next((line.split("=", 1)[1].strip() for line in env.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("DATABASE_URL=")), None)
    if not url:
        raise SystemExit(f"DATABASE_URL not found in {env}")
    engine = create_engine(url, connect_args={"options": f"-c timezone={PLANT_TZ}"})
    return sessionmaker(bind=engine)()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write 5-minute snapshot files sampled from stored telemetry.")
    parser.add_argument("--start", type=datetime.fromisoformat, help='first interval, e.g. "2026-09-29 00:00"')
    parser.add_argument("--end", type=datetime.fromisoformat, help="last interval (included)")
    parser.add_argument("--seed", type=int, help="same seed + same range = the same files")
    parser.add_argument("--overwrite", action="store_true", help="replace files of the same name still waiting in the inbox")
    parser.add_argument("--source-from", type=date.fromisoformat, help="sample only from historical days on/after this")
    parser.add_argument("--source-to", type=date.fromisoformat, help="sample only from historical days on/before this")
    parser.add_argument("--inbox", type=Path, default=INBOX, help=f"where to write (default {INBOX})")
    parser.add_argument("--info", action="store_true", help="show what can be sampled and exit")
    args = parser.parse_args(argv)

    db = session()
    try:
        if args.info:
            info = source_info(db)
            days = info["source_days"]
            print(f"Battery system : {info['system_name']}")
            print(f"Source days    : {len(days)}" + (f" ({days[0]} -> {days[-1]})" if days else ""))
            print(f"Module days    : {', '.join(info['module_days']) or 'none'}")
            print(f"Latest stored  : {info['latest_telemetry']}")
            print(f"Writes to      : {info['inbox']} (max {info['max_files']} files per run)")
            return 0
        if not args.start or not args.end:
            parser.error("--start and --end are required (or use --info)")
        try:
            result = simulate(db, args.start, args.end, seed=args.seed, overwrite=args.overwrite,
                              source_from=args.source_from, source_to=args.source_to, inbox=args.inbox)
        except SimulatorError as exc:
            print(f"ERROR: {exc}")
            return 1
    finally:
        db.close()

    files = f": {result.first_file} .. {result.last_file}" if result.written else ""
    print(f"{result.written} file(s) written to {args.inbox}{files}")
    print(f"  {result.start:%Y-%m-%d %H:%M} -> {result.end:%Y-%m-%d %H:%M}, {result.intervals} interval(s)"
          + (f", {result.skipped_existing} skipped (already waiting)" if result.skipped_existing else ""))
    for day, source in result.source_days.items():
        print(f"  {day} replays {source}")
    for warning in result.warnings:
        print(f"  WARNING: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

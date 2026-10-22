"""Micro-batch for scheduled runs: every system's default multivariate anomaly model scores its newest telemetry
into the model's live run (re-scored windows are upserted). From "ML model/service":

    ..\..\.venv\Scripts\python -m usecases.mv_anomaly.batch                 # all systems with a model, last 2 h
    ..\..\.venv\Scripts\python -m usecases.mv_anomaly.batch --system 12 --hours 24
"""
import argparse
import json

from usecases.mv_anomaly.router import live_score


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the newest telemetry with each system's default anomaly model")
    ap.add_argument("--system", type=int, help="battery_system_id (default: every system with a built model)")
    ap.add_argument("--hours", type=int, default=2, help="window to (re)score, ending at the newest reading")
    args = ap.parse_args()
    print(json.dumps(live_score(args.system, args.hours), indent=2, default=str))


if __name__ == "__main__":
    main()

"""Point the weather hypertables at the real weather stations.

    python 2026_10_03_weather_fk.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_03_weather_fk.py --commit   # run for real

battery_telemetry.weather_actual and weather_forecast referenced battery_telemetry.weather_station - an empty
two-column stub - while the stations (code, site, provider, coordinates) live in battery_master.weather_station.
With the stub empty no weather reading could be stored. Both foreign keys now reference
battery_master.weather_station; the stub table is left untouched.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    "ALTER TABLE battery_telemetry.weather_actual DROP CONSTRAINT weather_actual_station_id_fkey",
    """ALTER TABLE battery_telemetry.weather_actual ADD CONSTRAINT weather_actual_station_id_fkey
       FOREIGN KEY (station_id) REFERENCES battery_master.weather_station (station_id)""",
    "ALTER TABLE battery_telemetry.weather_forecast DROP CONSTRAINT weather_forecast_station_id_fkey",
    """ALTER TABLE battery_telemetry.weather_forecast ADD CONSTRAINT weather_forecast_station_id_fkey
       FOREIGN KEY (station_id) REFERENCES battery_master.weather_station (station_id)""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for t in ("weather_actual", "weather_forecast"):
        cur.execute(f"SELECT count(*) FROM battery_telemetry.{t}")
        print(f"   {t} rows:", cur.fetchone()[0])
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("""SELECT conrelid::regclass::text, confrelid::regclass::text,
                          (SELECT relnamespace::regnamespace::text FROM pg_class WHERE oid = confrelid)
                   FROM pg_constraint WHERE conname IN ('weather_actual_station_id_fkey', 'weather_forecast_station_id_fkey')""")
    for row in cur.fetchall():
        print("  ", row)
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)

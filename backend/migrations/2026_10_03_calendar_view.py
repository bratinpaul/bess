"""Read the calendar for net-load features from the reference calendar.

    python 2026_10_03_calendar_view.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_03_calendar_view.py --commit   # run for real

battery_telemetry.v_netload_features joined battery_telemetry.calendar_day - an empty four-column stub - while the
calendar is maintained in battery_master.calendar_day (Core -> Reference -> Calendar). The view now joins the
reference table; its columns and their types are unchanged. The stub table is left untouched.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

VIEW = """
CREATE OR REPLACE VIEW battery_telemetry.v_netload_features AS
SELECT d.metering_point_id,
       d.ts,
       d.net_load_kw,
       d.gross_load_kw,
       d.behind_meter_gen_kw,
       d.load_reactive_kvar,
       w.temp_c,
       w.ghi_wm2,
       w.humidity_pct,
       w.wind_ms,
       w.cloud_fraction,
       c.day_type,
       c.is_weekend,
       c.is_holiday,
       EXTRACT(hour FROM d.ts) AS hour_of_day,
       EXTRACT(dow FROM d.ts) AS day_of_week,
       EXTRACT(doy FROM d.ts) AS day_of_year
FROM battery_telemetry.demand_telemetry d
LEFT JOIN battery_telemetry.weather_actual w ON w.ts = d.ts
LEFT JOIN battery_master.calendar_day c ON c.calendar_date = (d.ts AT TIME ZONE 'Asia/Kolkata')::date
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute(VIEW)
    cur.execute("COMMENT ON VIEW battery_telemetry.v_netload_features IS "
                "'Training features for net-load/peak forecasting (target = net_load_kw); calendar from battery_master.calendar_day.'")
    cur.execute("""SELECT DISTINCT n.nspname || '.' || t.relname
                   FROM pg_depend dp JOIN pg_rewrite r ON r.oid = dp.objid
                   JOIN pg_class t ON t.oid = dp.refobjid JOIN pg_namespace n ON n.oid = t.relnamespace
                   WHERE r.ev_class = 'battery_telemetry.v_netload_features'::regclass AND t.relname = 'calendar_day'""")
    print("   view reads:", [r[0] for r in cur.fetchall()])
    cur.execute("SELECT count(*) FROM battery_telemetry.v_netload_features")
    print("   view rows:", cur.fetchone()[0])
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)

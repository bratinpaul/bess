"""Reshape battery_telemetry.alarm_event for the alarm log (BESS_Alarm_SampleData.xlsx, 'Alarms' sheet).

    python 2026_09_27_alarm_event.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_27_alarm_event.py --commit   # run for real

The table was an empty hypertable (time, alarm_code, severity, description, active, acknowledged, asset_id)
that nothing used. It stays a hypertable on "time" (= the alarm's start time) and becomes:

    alarm_id           ALM-00001 ...; key (alarm_id, time) - a hypertable key must include its time column
    alarm_catalog_id   -> alarm_catalog: source, alarm code, type, description and probable cause come from there
    severity_level     -> alarm_severity: the severity it fired with (defaults to the catalog's)
    asset_type, asset_code          what the source reported, e.g. 'Pack' / 'PACK-01'
    linked_asset_type, linked_asset_id, asset_match
                                    the master-data record it was matched to (e.g. battery_pack 1) and how
                                    (exact / fuzzy / manual); battery_system_id is that record's battery system
    end_time           NULL while the alarm is active
    trigger_value, threshold_value, unit
    acknowledged_by, acknowledged_at

Status (Active / Cleared), duration and start date are derived by the API, not stored.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
T = "battery_telemetry.alarm_event"

STEPS = [
    f"ALTER TABLE {T} DROP CONSTRAINT alarm_event_pkey",
    f"ALTER TABLE {T} DROP COLUMN alarm_code, DROP COLUMN severity, DROP COLUMN description, "
    "DROP COLUMN active, DROP COLUMN acknowledged, DROP COLUMN asset_id",
    f"""ALTER TABLE {T}
        ADD COLUMN alarm_id          text        NOT NULL,
        ADD COLUMN alarm_catalog_id  bigint      NOT NULL REFERENCES battery_master.alarm_catalog (alarm_catalog_id),
        ADD COLUMN severity_level    smallint    NOT NULL REFERENCES battery_master.alarm_severity (severity_level),
        ADD COLUMN asset_type        text,
        ADD COLUMN asset_code        text,
        ADD COLUMN linked_asset_type text,
        ADD COLUMN linked_asset_id   bigint,
        ADD COLUMN asset_match       text,
        ADD COLUMN battery_system_id bigint      REFERENCES battery_master.battery_system (battery_system_id) ON DELETE SET NULL,
        ADD COLUMN end_time          timestamptz,
        ADD COLUMN trigger_value     numeric,
        ADD COLUMN threshold_value   numeric,
        ADD COLUMN unit              text,
        ADD COLUMN acknowledged_by   text,
        ADD COLUMN acknowledged_at   timestamptz,
        ADD COLUMN created_at        timestamptz NOT NULL DEFAULT now(),
        ADD COLUMN updated_at        timestamptz NOT NULL DEFAULT now()""",
    f"ALTER TABLE {T} ADD CONSTRAINT alarm_event_pkey PRIMARY KEY (alarm_id, time)",
    f"ALTER TABLE {T} ADD CONSTRAINT alarm_event_id_not_blank CHECK (btrim(alarm_id) <> '')",
    f"ALTER TABLE {T} ADD CONSTRAINT alarm_event_end_after_start CHECK (end_time IS NULL OR end_time >= time)",
    # who and when go together, and an alarm can't be acknowledged before it fired
    f"ALTER TABLE {T} ADD CONSTRAINT alarm_event_ack_pair CHECK ((acknowledged_by IS NULL) = (acknowledged_at IS NULL))",
    f"ALTER TABLE {T} ADD CONSTRAINT alarm_event_ack_after_start CHECK (acknowledged_at IS NULL OR acknowledged_at >= time)",
    f"""ALTER TABLE {T} ADD CONSTRAINT alarm_event_link_pair
        CHECK ((linked_asset_type IS NULL) = (linked_asset_id IS NULL))""",
    f"""ALTER TABLE {T} ADD CONSTRAINT alarm_event_asset_match_kind
        CHECK (asset_match IS NULL OR asset_match IN ('exact', 'fuzzy', 'manual'))""",
    f"CREATE INDEX idx_alarm_event_system_time ON {T} (battery_system_id, time DESC)",
    f"CREATE INDEX idx_alarm_event_catalog_time ON {T} (alarm_catalog_id, time DESC)",
    f"CREATE INDEX idx_alarm_event_active ON {T} (time DESC) WHERE end_time IS NULL",
    f"COMMENT ON TABLE {T} IS 'Alarm occurrences (raise -> clear); key (alarm_id, time); time = start time'",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute(f"SELECT count(*) FROM {T}")
    assert cur.fetchone()[0] == 0, "alarm_event is not empty - refusing to reshape it"
    for sql in STEPS:
        cur.execute(sql)
    cur.execute(
        """SELECT column_name, data_type, is_nullable FROM information_schema.columns
           WHERE table_schema = 'battery_telemetry' AND table_name = 'alarm_event' ORDER BY ordinal_position"""
    )
    for row in cur.fetchall():
        print("  ", row)
    cur.execute("SELECT hypertable_name, num_dimensions FROM timescaledb_information.hypertables WHERE hypertable_name = 'alarm_event'")
    print("   hypertable:", cur.fetchall())
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)

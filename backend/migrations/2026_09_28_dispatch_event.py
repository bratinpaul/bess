"""Reshape battery_telemetry.dispatch_event for the EMS dispatch log
(BESS_DispatchEvents_SampleData.xlsx, 'Dispatch Events' sheet).

    python 2026_09_28_dispatch_event.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_28_dispatch_event.py --commit   # run for real

The table was an empty hypertable (time, event_type, power_mw, energy_mwh, market_price, battery_system_id)
that nothing used. It stays a hypertable on "time" (= effective_from, when the dispatch took effect) and becomes:

    dispatch_id        DSP-00001 ...; key (dispatch_id, time) - a hypertable key must include its time column
    ems_id             -> ems_controller (the file's ems_code); battery_system_id is that EMS's battery system
    command_code       SET_MODE / SET_POWER / SET_SERVICE
    dispatch_mode      -> ems_dispatch_mode (STANDBY, SCHEDULED_CHARGE, ENERGY_ARBITRAGE, ...)
    grid_service       -> ems_grid_service (NONE, ARBITRAGE, FREQ_REG)
    source             who issued it: Scheduler, Market optimizer, AGC, ...
    issued_at          when the command was issued (not after it took effect)
    effective_to       NULL while the dispatch is active
    p_setpoint_kw      > 0 charge / import, < 0 discharge / export
    target_soc_pct, soc_start_pct, soc_end_pct, ramp_rate_kw_s
    import_kwh, export_kwh, avg_price_mwh, revenue_usd   realised over the window
    accepted, status (Active / Completed / Aborted), note

Duration, net energy (import - export) and the issued date are derived by the API, not stored.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
T = "battery_telemetry.dispatch_event"

STEPS = [
    f"ALTER TABLE {T} DROP CONSTRAINT dispatch_event_pkey",
    f"ALTER TABLE {T} DROP COLUMN event_type, DROP COLUMN power_mw, DROP COLUMN energy_mwh, DROP COLUMN market_price",
    f"ALTER TABLE {T} ALTER COLUMN battery_system_id DROP NOT NULL",
    f"""ALTER TABLE {T} ADD CONSTRAINT dispatch_event_system_fkey FOREIGN KEY (battery_system_id)
        REFERENCES battery_master.battery_system (battery_system_id) ON DELETE SET NULL""",
    f"""ALTER TABLE {T}
        ADD COLUMN dispatch_id     text        NOT NULL,
        ADD COLUMN ems_id          bigint      NOT NULL REFERENCES battery_master.ems_controller (ems_id),
        ADD COLUMN command_code    text        NOT NULL,
        ADD COLUMN dispatch_mode   text        NOT NULL REFERENCES battery_master.ems_dispatch_mode (mode_code),
        ADD COLUMN grid_service    text        NOT NULL DEFAULT 'NONE' REFERENCES battery_master.ems_grid_service (service_code),
        ADD COLUMN source          text,
        ADD COLUMN issued_at       timestamptz NOT NULL,
        ADD COLUMN effective_to    timestamptz,
        ADD COLUMN p_setpoint_kw   numeric     NOT NULL DEFAULT 0,
        ADD COLUMN target_soc_pct  numeric,
        ADD COLUMN soc_start_pct   numeric,
        ADD COLUMN soc_end_pct     numeric,
        ADD COLUMN ramp_rate_kw_s  numeric,
        ADD COLUMN import_kwh      numeric     NOT NULL DEFAULT 0,
        ADD COLUMN export_kwh      numeric     NOT NULL DEFAULT 0,
        ADD COLUMN avg_price_mwh   numeric,
        ADD COLUMN revenue_usd     numeric,
        ADD COLUMN accepted        boolean     NOT NULL DEFAULT true,
        ADD COLUMN status          text        NOT NULL,
        ADD COLUMN note            text,
        ADD COLUMN created_at      timestamptz NOT NULL DEFAULT now(),
        ADD COLUMN updated_at      timestamptz NOT NULL DEFAULT now()""",
    f"ALTER TABLE {T} ADD CONSTRAINT dispatch_event_pkey PRIMARY KEY (dispatch_id, time)",
    f"ALTER TABLE {T} ADD CONSTRAINT dispatch_event_id_not_blank CHECK (btrim(dispatch_id) <> '')",
    f"""ALTER TABLE {T} ADD CONSTRAINT dispatch_event_command_code
        CHECK (command_code IN ('SET_MODE', 'SET_POWER', 'SET_SERVICE'))""",
    f"ALTER TABLE {T} ADD CONSTRAINT dispatch_event_status CHECK (status IN ('Active', 'Completed', 'Aborted'))",
    # an active dispatch has no end yet; a completed or aborted one has
    f"ALTER TABLE {T} ADD CONSTRAINT dispatch_event_active_open CHECK ((status = 'Active') = (effective_to IS NULL))",
    f"ALTER TABLE {T} ADD CONSTRAINT dispatch_event_end_after_start CHECK (effective_to IS NULL OR effective_to >= time)",
    f"ALTER TABLE {T} ADD CONSTRAINT dispatch_event_issued_first CHECK (issued_at <= time)",
    f"""ALTER TABLE {T} ADD CONSTRAINT dispatch_event_soc_range CHECK (
        (target_soc_pct IS NULL OR target_soc_pct BETWEEN 0 AND 100) AND
        (soc_start_pct  IS NULL OR soc_start_pct  BETWEEN 0 AND 100) AND
        (soc_end_pct    IS NULL OR soc_end_pct    BETWEEN 0 AND 100))""",
    f"""ALTER TABLE {T} ADD CONSTRAINT dispatch_event_non_negative CHECK (
        import_kwh >= 0 AND export_kwh >= 0 AND (ramp_rate_kw_s IS NULL OR ramp_rate_kw_s >= 0))""",
    f"CREATE INDEX idx_dispatch_event_ems_time ON {T} (ems_id, time DESC)",
    f"CREATE INDEX idx_dispatch_event_system_time ON {T} (battery_system_id, time DESC)",
    f"CREATE INDEX idx_dispatch_event_mode_time ON {T} (dispatch_mode, time DESC)",
    f"COMMENT ON TABLE {T} IS 'EMS dispatch instructions; key (dispatch_id, time); time = effective_from'",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute(f"SELECT count(*) FROM {T}")
    assert cur.fetchone()[0] == 0, "dispatch_event is not empty - refusing to reshape it"
    for sql in STEPS:
        cur.execute(sql)
    cur.execute(
        """SELECT column_name, data_type, is_nullable FROM information_schema.columns
           WHERE table_schema = 'battery_telemetry' AND table_name = 'dispatch_event' ORDER BY ordinal_position"""
    )
    for row in cur.fetchall():
        print("  ", row)
    cur.execute("SELECT hypertable_name, num_dimensions FROM timescaledb_information.hypertables WHERE hypertable_name = 'dispatch_event'")
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

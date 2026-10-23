-- BESS database DDL: battery_telemetry
-- Generated 2026-10-23 by db_docs/generate_ddl.py from database Battery
-- Sections: extensions, pg_dump schema DDL, TimescaleDB hypertables + compression, continuous aggregates,
--           views on continuous aggregates, TimescaleDB policies

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================ schema DDL (pg_dump)
--
-- PostgreSQL database dump
--

\restrict ilBNdFvvXHcech06yvBnLBYLVm8FCwLiRD1xuWSdA8rMlo9axpfDzoSGHcHYTr0

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: battery_telemetry; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_telemetry;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: pcs_telemetry; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.pcs_telemetry (
    pcs_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    mode_code text,
    grid_service text,
    ac_active_power_kw numeric(9,2),
    ac_reactive_power_kvar numeric(9,2),
    ac_apparent_power_kva numeric(9,2),
    power_factor numeric(5,3),
    ac_frequency_hz numeric(6,3),
    ac_voltage_ab_v numeric(8,2),
    ac_voltage_bc_v numeric(8,2),
    ac_voltage_ca_v numeric(8,2),
    ac_current_a_a numeric(9,2),
    ac_current_b_a numeric(9,2),
    ac_current_c_a numeric(9,2),
    thd_voltage_pct numeric(5,2),
    thd_current_pct numeric(5,2),
    dc_voltage_v numeric(8,2),
    dc_current_a numeric(9,2),
    dc_power_kw numeric(9,2),
    efficiency_pct numeric(5,2),
    igbt_temp_c numeric(6,2),
    heatsink_temp_c numeric(6,2),
    inlet_coolant_temp_c numeric(6,2),
    ambient_temp_c numeric(6,2),
    avail_charge_kw numeric(9,2),
    avail_discharge_kw numeric(9,2),
    ac_energy_import_kwh numeric(13,2),
    ac_energy_export_kwh numeric(13,2),
    breaker_state text,
    alarm_level smallint,
    CONSTRAINT chk_eff CHECK (((efficiency_pct IS NULL) OR ((efficiency_pct >= (0)::numeric) AND (efficiency_pct <= (100)::numeric)))),
    CONSTRAINT chk_freq CHECK (((ac_frequency_hz IS NULL) OR ((ac_frequency_hz >= (0)::numeric) AND (ac_frequency_hz <= (100)::numeric)))),
    CONSTRAINT chk_pf CHECK (((power_factor IS NULL) OR ((power_factor >= ('-1'::integer)::numeric) AND (power_factor <= (1)::numeric))))
);


--
-- Name: TABLE pcs_telemetry; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON TABLE battery_telemetry.pcs_telemetry IS 'PCS AC/DC/thermal telemetry (TimescaleDB hypertable), sampled every 5 min.';


--
-- Name: ems_telemetry; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.ems_telemetry (
    ems_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    dispatch_mode text,
    grid_service text,
    market_price_mwh numeric(10,2),
    p_setpoint_kw numeric(10,2),
    poi_active_power_kw numeric(10,2),
    poi_reactive_power_kvar numeric(10,2),
    tracking_error_kw numeric(10,2),
    grid_frequency_hz numeric(6,3),
    poi_voltage_kv numeric(8,3),
    agc_signal numeric(6,3),
    plant_soc_pct numeric(5,2),
    target_soc_pct numeric(5,2),
    avail_charge_kw numeric(10,2),
    avail_discharge_kw numeric(10,2),
    avail_charge_energy_kwh numeric(12,2),
    avail_discharge_energy_kwh numeric(12,2),
    aux_load_kw numeric(9,2),
    aux_load_pct numeric(6,2),
    cum_import_kwh numeric(14,2),
    cum_export_kwh numeric(14,2),
    revenue_cum_usd numeric(14,2),
    units_online smallint,
    plant_available smallint,
    alarm_level smallint,
    CONSTRAINT chk_ems_agc CHECK (((agc_signal IS NULL) OR ((agc_signal >= ('-1'::integer)::numeric) AND (agc_signal <= (1)::numeric)))),
    CONSTRAINT chk_ems_alarm CHECK (((alarm_level IS NULL) OR ((alarm_level >= 0) AND (alarm_level <= 3)))),
    CONSTRAINT chk_ems_avail CHECK (((plant_available IS NULL) OR (plant_available = ANY (ARRAY[0, 1])))),
    CONSTRAINT chk_ems_freq CHECK (((grid_frequency_hz IS NULL) OR ((grid_frequency_hz >= (0)::numeric) AND (grid_frequency_hz <= (100)::numeric)))),
    CONSTRAINT chk_ems_price CHECK (((market_price_mwh IS NULL) OR (market_price_mwh >= (0)::numeric))),
    CONSTRAINT chk_ems_soc CHECK (((plant_soc_pct IS NULL) OR ((plant_soc_pct >= (0)::numeric) AND (plant_soc_pct <= (100)::numeric)))),
    CONSTRAINT chk_ems_tsoc CHECK (((target_soc_pct IS NULL) OR ((target_soc_pct >= (0)::numeric) AND (target_soc_pct <= (100)::numeric))))
);


--
-- Name: TABLE ems_telemetry; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON TABLE battery_telemetry.ems_telemetry IS 'Plant/EMS telemetry (TimescaleDB hypertable): POI metering, dispatch, SOC, market — sampled every 5 min.';


--
-- Name: hvac_telemetry; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.hvac_telemetry (
    hvac_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    cooling_mode text,
    ambient_temp_c numeric(6,2),
    coolant_setpoint_c numeric(5,2),
    coolant_supply_temp_c numeric(6,2),
    coolant_return_temp_c numeric(6,2),
    coolant_delta_t_c numeric(6,2),
    coolant_flow_lpm numeric(8,2),
    compressor_speed_pct numeric(5,2),
    condenser_fan_pct numeric(5,2),
    refrig_suction_bar numeric(7,2),
    refrig_discharge_bar numeric(7,2),
    battery_heat_load_kw numeric(9,2),
    cooling_capacity_kw numeric(9,2),
    heat_rejected_kw numeric(9,2),
    hvac_power_kw numeric(9,2),
    cop numeric(5,2),
    enclosure_temp_c numeric(6,2),
    enclosure_humidity_pct numeric(5,2),
    filter_dp_pa numeric(8,1),
    cum_energy_kwh numeric(13,2),
    compressor_runtime_h numeric(10,2),
    units_running smallint,
    alarm_level smallint,
    alarm_flags text,
    CONSTRAINT chk_hvac_alarm CHECK (((alarm_level IS NULL) OR ((alarm_level >= 0) AND (alarm_level <= 3)))),
    CONSTRAINT chk_hvac_comp CHECK (((compressor_speed_pct IS NULL) OR ((compressor_speed_pct >= (0)::numeric) AND (compressor_speed_pct <= (100)::numeric)))),
    CONSTRAINT chk_hvac_cop CHECK (((cop IS NULL) OR (cop >= (0)::numeric))),
    CONSTRAINT chk_hvac_fan CHECK (((condenser_fan_pct IS NULL) OR ((condenser_fan_pct >= (0)::numeric) AND (condenser_fan_pct <= (100)::numeric)))),
    CONSTRAINT chk_hvac_flow CHECK (((coolant_flow_lpm IS NULL) OR (coolant_flow_lpm >= (0)::numeric))),
    CONSTRAINT chk_hvac_rh CHECK (((enclosure_humidity_pct IS NULL) OR ((enclosure_humidity_pct >= (0)::numeric) AND (enclosure_humidity_pct <= (100)::numeric))))
);


--
-- Name: TABLE hvac_telemetry; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON TABLE battery_telemetry.hvac_telemetry IS 'Container HVAC/TMS telemetry (TimescaleDB hypertable), sampled every 5 min.';


--
-- Name: system_telemetry; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.system_telemetry (
    ts timestamp with time zone NOT NULL,
    mode_code text,
    soc_bms_pct numeric(5,2),
    soh_pct numeric(5,2),
    pack_voltage_v numeric(8,2),
    pack_current_a numeric(9,2),
    power_kw numeric(9,2),
    c_rate numeric(6,3),
    cell_v_avg_v numeric(6,4),
    cell_v_min_v numeric(6,4),
    cell_v_max_v numeric(6,4),
    cell_v_delta_mv numeric(7,2),
    cell_temp_avg_c numeric(6,2),
    cell_temp_min_c numeric(6,2),
    cell_temp_max_c numeric(6,2),
    coolant_temp_c numeric(6,2),
    ambient_temp_c numeric(6,2),
    insulation_res_kohm numeric(9,1),
    avail_charge_kw numeric(9,2),
    avail_discharge_kw numeric(9,2),
    cum_charge_kwh numeric(12,2),
    cum_discharge_kwh numeric(12,2),
    equiv_full_cycles numeric(10,3),
    contactor_state text,
    alarm_level smallint,
    system_id bigint NOT NULL,
    measured_current_a numeric(9,2),
    current_sensor_offset_a numeric(7,3),
    soc_coulomb_pct numeric(5,2),
    soc_battery_telemetry_pct numeric(5,2),
    usable_capacity_ah numeric(9,2),
    coulombic_efficiency numeric(6,4),
    at_rest boolean,
    rest_duration_min numeric(7,1),
    ocv_rested_v numeric(6,4),
    CONSTRAINT chk_soc CHECK (((soc_bms_pct IS NULL) OR ((soc_bms_pct >= (0)::numeric) AND (soc_bms_pct <= (100)::numeric)))),
    CONSTRAINT chk_soh CHECK (((soh_pct IS NULL) OR ((soh_pct >= (0)::numeric) AND (soh_pct <= (100)::numeric)))),
    CONSTRAINT chk_tord CHECK (((cell_temp_min_c IS NULL) OR (cell_temp_max_c IS NULL) OR (cell_temp_min_c <= cell_temp_max_c))),
    CONSTRAINT chk_vord CHECK (((cell_v_min_v IS NULL) OR (cell_v_max_v IS NULL) OR (cell_v_min_v <= cell_v_max_v)))
);


--
-- Name: TABLE system_telemetry; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON TABLE battery_telemetry.system_telemetry IS 'System-level telemetry (TimescaleDB hypertable), sampled every 5 min.';


--
-- Name: COLUMN system_telemetry.soc_bms_pct; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON COLUMN battery_telemetry.system_telemetry.soc_bms_pct IS 'BMS fused SOC estimate (the reported value).';


--
-- Name: COLUMN system_telemetry.soc_coulomb_pct; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON COLUMN battery_telemetry.system_telemetry.soc_coulomb_pct IS 'Raw coulomb-counted SOC; drifts with sensor error between recalibrations.';


--
-- Name: module_telemetry; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.module_telemetry (
    module_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    cell_v_avg_v numeric(6,4),
    cell_v_min_v numeric(6,4),
    cell_v_max_v numeric(6,4),
    cell_temp_max_c numeric(6,2),
    cell_temp_min_c numeric(6,2),
    balancing_active boolean,
    CONSTRAINT chk_mod_tord CHECK (((cell_temp_min_c IS NULL) OR (cell_temp_max_c IS NULL) OR (cell_temp_min_c <= cell_temp_max_c))),
    CONSTRAINT chk_mod_vord CHECK (((cell_v_min_v IS NULL) OR (cell_v_max_v IS NULL) OR (cell_v_min_v <= cell_v_max_v)))
);


--
-- Name: demand_telemetry; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.demand_telemetry (
    metering_point_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    gross_load_kw numeric(12,2),
    behind_meter_gen_kw numeric(12,2),
    net_load_kw numeric(12,2),
    load_reactive_kvar numeric(12,2)
);


--
-- Name: TABLE demand_telemetry; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON TABLE battery_telemetry.demand_telemetry IS 'Feeder demand, behind-meter generation and net load (TimescaleDB hypertable).';


--
-- Name: alarm_event; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.alarm_event (
    "time" timestamp with time zone NOT NULL,
    alarm_id text NOT NULL,
    alarm_catalog_id bigint NOT NULL,
    severity_level smallint NOT NULL,
    asset_type text,
    asset_code text,
    linked_asset_type text,
    linked_asset_id bigint,
    asset_match text,
    battery_system_id bigint,
    end_time timestamp with time zone,
    trigger_value numeric,
    threshold_value numeric,
    unit text,
    acknowledged_by text,
    acknowledged_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT alarm_event_ack_after_start CHECK (((acknowledged_at IS NULL) OR (acknowledged_at >= "time"))),
    CONSTRAINT alarm_event_ack_pair CHECK (((acknowledged_by IS NULL) = (acknowledged_at IS NULL))),
    CONSTRAINT alarm_event_asset_match_kind CHECK (((asset_match IS NULL) OR (asset_match = ANY (ARRAY['exact'::text, 'fuzzy'::text, 'manual'::text])))),
    CONSTRAINT alarm_event_end_after_start CHECK (((end_time IS NULL) OR (end_time >= "time"))),
    CONSTRAINT alarm_event_id_not_blank CHECK ((btrim(alarm_id) <> ''::text)),
    CONSTRAINT alarm_event_link_pair CHECK (((linked_asset_type IS NULL) = (linked_asset_id IS NULL)))
);


--
-- Name: TABLE alarm_event; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON TABLE battery_telemetry.alarm_event IS 'Alarm occurrences (raise -> clear); key (alarm_id, time); time = start time';


--
-- Name: dispatch_event; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.dispatch_event (
    "time" timestamp with time zone NOT NULL,
    battery_system_id bigint,
    dispatch_id text NOT NULL,
    ems_id bigint NOT NULL,
    command_code text NOT NULL,
    dispatch_mode text NOT NULL,
    grid_service text DEFAULT 'NONE'::text NOT NULL,
    source text,
    issued_at timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    p_setpoint_kw numeric DEFAULT 0 NOT NULL,
    target_soc_pct numeric,
    soc_start_pct numeric,
    soc_end_pct numeric,
    ramp_rate_kw_s numeric,
    import_kwh numeric DEFAULT 0 NOT NULL,
    export_kwh numeric DEFAULT 0 NOT NULL,
    avg_price_mwh numeric,
    revenue_usd numeric,
    accepted boolean DEFAULT true NOT NULL,
    status text NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT dispatch_event_active_open CHECK (((status = 'Active'::text) = (effective_to IS NULL))),
    CONSTRAINT dispatch_event_command_code CHECK ((command_code = ANY (ARRAY['SET_MODE'::text, 'SET_POWER'::text, 'SET_SERVICE'::text]))),
    CONSTRAINT dispatch_event_end_after_start CHECK (((effective_to IS NULL) OR (effective_to >= "time"))),
    CONSTRAINT dispatch_event_id_not_blank CHECK ((btrim(dispatch_id) <> ''::text)),
    CONSTRAINT dispatch_event_issued_first CHECK ((issued_at <= "time")),
    CONSTRAINT dispatch_event_non_negative CHECK (((import_kwh >= (0)::numeric) AND (export_kwh >= (0)::numeric) AND ((ramp_rate_kw_s IS NULL) OR (ramp_rate_kw_s >= (0)::numeric)))),
    CONSTRAINT dispatch_event_soc_range CHECK ((((target_soc_pct IS NULL) OR ((target_soc_pct >= (0)::numeric) AND (target_soc_pct <= (100)::numeric))) AND ((soc_start_pct IS NULL) OR ((soc_start_pct >= (0)::numeric) AND (soc_start_pct <= (100)::numeric))) AND ((soc_end_pct IS NULL) OR ((soc_end_pct >= (0)::numeric) AND (soc_end_pct <= (100)::numeric))))),
    CONSTRAINT dispatch_event_status CHECK ((status = ANY (ARRAY['Active'::text, 'Completed'::text, 'Aborted'::text])))
);


--
-- Name: TABLE dispatch_event; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON TABLE battery_telemetry.dispatch_event IS 'EMS dispatch instructions; key (dispatch_id, time); time = effective_from';


--
-- Name: weather_actual; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.weather_actual (
    station_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    temp_c numeric(6,2),
    ghi_wm2 numeric(8,1),
    humidity_pct numeric(5,1),
    wind_ms numeric(5,1),
    cloud_fraction numeric(4,3),
    CONSTRAINT chk_wx_cloud CHECK (((cloud_fraction IS NULL) OR ((cloud_fraction >= (0)::numeric) AND (cloud_fraction <= (1)::numeric))))
);


--
-- Name: weather_forecast; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.weather_forecast (
    station_id bigint NOT NULL,
    issued_at timestamp with time zone NOT NULL,
    valid_at timestamp with time zone NOT NULL,
    temp_c numeric(6,2),
    ghi_wm2 numeric(8,1)
);


--
-- Name: TABLE weather_forecast; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON TABLE battery_telemetry.weather_forecast IS 'Day-ahead weather forecast; issued_at = vintage, valid_at = target time.';


--
-- Name: calendar_day; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.calendar_day (
    calendar_date date NOT NULL,
    day_type text,
    is_weekend boolean,
    is_holiday boolean
);


--
-- Name: metering_point; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.metering_point (
    metering_point_id bigint NOT NULL,
    mp_code text
);


--
-- Name: metering_point_metering_point_id_seq; Type: SEQUENCE; Schema: battery_telemetry; Owner: -
--

ALTER TABLE battery_telemetry.metering_point ALTER COLUMN metering_point_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_telemetry.metering_point_metering_point_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: v_ems_latest; Type: VIEW; Schema: battery_telemetry; Owner: -
--

CREATE VIEW battery_telemetry.v_ems_latest AS
 SELECT DISTINCT ON (t.ems_id) t.ems_id,
    e.ems_code,
    t.ts,
    t.dispatch_mode,
    t.grid_service,
    t.poi_active_power_kw,
    t.plant_soc_pct,
    t.target_soc_pct,
    t.market_price_mwh,
    t.grid_frequency_hz,
    t.revenue_cum_usd,
    t.plant_available,
    t.alarm_level
   FROM (battery_telemetry.ems_telemetry t
     JOIN battery_master.ems_controller e ON ((e.ems_id = t.ems_id)))
  ORDER BY t.ems_id, t.ts DESC;


--
-- Name: VIEW v_ems_latest; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON VIEW battery_telemetry.v_ems_latest IS 'Most recent EMS telemetry row per controller.';


--
-- Name: v_hvac_latest; Type: VIEW; Schema: battery_telemetry; Owner: -
--

CREATE VIEW battery_telemetry.v_hvac_latest AS
 SELECT DISTINCT ON (t.hvac_id) t.hvac_id,
    u.hvac_code,
    t.ts,
    t.cooling_mode,
    t.coolant_supply_temp_c,
    t.coolant_return_temp_c,
    t.battery_heat_load_kw,
    t.hvac_power_kw,
    t.cop,
    t.enclosure_temp_c,
    t.alarm_level,
    t.alarm_flags
   FROM (battery_telemetry.hvac_telemetry t
     JOIN battery_master.hvac_unit u ON ((u.hvac_id = t.hvac_id)))
  ORDER BY t.hvac_id, t.ts DESC;


--
-- Name: VIEW v_hvac_latest; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON VIEW battery_telemetry.v_hvac_latest IS 'Most recent HVAC telemetry row per unit.';


--
-- Name: v_module_latest; Type: VIEW; Schema: battery_telemetry; Owner: -
--

CREATE VIEW battery_telemetry.v_module_latest AS
 SELECT DISTINCT ON (t.module_id) t.module_id,
    t.ts,
    t.cell_v_avg_v,
    t.cell_v_min_v,
    t.cell_v_max_v,
    ((t.cell_v_max_v - t.cell_v_min_v) * 1000.0) AS imbalance_mv,
    t.cell_temp_max_c,
    t.balancing_active
   FROM (battery_telemetry.module_telemetry t
     JOIN battery_master.battery_module m ON ((m.module_id = t.module_id)))
  ORDER BY t.module_id, t.ts DESC;


--
-- Name: v_netload_features; Type: VIEW; Schema: battery_telemetry; Owner: -
--

CREATE VIEW battery_telemetry.v_netload_features AS
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
   FROM ((battery_telemetry.demand_telemetry d
     LEFT JOIN battery_telemetry.weather_actual w ON ((w.ts = d.ts)))
     LEFT JOIN battery_master.calendar_day c ON ((c.calendar_date = ((d.ts AT TIME ZONE 'Asia/Kolkata'::text))::date)));


--
-- Name: VIEW v_netload_features; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON VIEW battery_telemetry.v_netload_features IS 'Training features for net-load/peak forecasting (target = net_load_kw); calendar from battery_master.calendar_day.';


--
-- Name: v_soh_daily_features; Type: VIEW; Schema: battery_telemetry; Owner: -
--

CREATE VIEW battery_telemetry.v_soh_daily_features AS
 WITH d AS (
         SELECT t.system_id,
            public.time_bucket('1 day'::interval, t.ts) AS day,
            public.last(t.soh_pct, t.ts) AS soh_pct,
            public.last(t.equiv_full_cycles, t.ts) AS equiv_full_cycles,
            public.last(t.cum_charge_kwh, t.ts) AS cum_charge_kwh,
            public.last(t.cum_discharge_kwh, t.ts) AS cum_discharge_kwh,
            ((sum(abs(t.power_kw)) * (5.0 / 60.0)) / 1000.0) AS daily_throughput_mwh,
            avg(t.soc_bms_pct) AS avg_soc_pct,
            min(t.soc_bms_pct) AS min_soc_pct,
            max(t.soc_bms_pct) AS max_soc_pct,
            (max(t.soc_bms_pct) - min(t.soc_bms_pct)) AS soc_swing_pct,
            ((count(*) FILTER (WHERE (t.soc_bms_pct > (90)::numeric)))::numeric * (5.0 / 60.0)) AS hours_soc_gt90,
            ((count(*) FILTER (WHERE (t.soc_bms_pct < (15)::numeric)))::numeric * (5.0 / 60.0)) AS hours_soc_lt15,
            avg(t.c_rate) AS avg_c_rate,
            max(t.c_rate) AS max_c_rate,
            ((count(*) FILTER (WHERE (t.c_rate > 0.7)))::numeric * (5.0 / 60.0)) AS hours_c_rate_gt0_7,
            max(t.cell_v_max_v) AS max_cell_voltage_v,
            min(t.cell_v_min_v) AS min_cell_voltage_v,
            avg(t.cell_v_delta_mv) AS avg_imbalance_mv,
            max(t.cell_v_delta_mv) AS max_imbalance_mv,
            avg(t.cell_temp_avg_c) AS avg_cell_temp_c,
            max(t.cell_temp_max_c) AS max_cell_temp_c,
            ((count(*) FILTER (WHERE (t.cell_temp_max_c > (35)::numeric)))::numeric * (5.0 / 60.0)) AS hours_temp_gt35,
            avg(t.ambient_temp_c) AS avg_ambient_c,
            count(*) AS sample_count
           FROM battery_telemetry.system_telemetry t
          GROUP BY t.system_id, (public.time_bucket('1 day'::interval, t.ts))
        )
 SELECT d.system_id,
    s.system_name,
    (d.day)::date AS day,
    ((d.day)::date - s.commissioned_on) AS calendar_age_days,
    d.soh_pct,
    (d.soh_pct - lag(d.soh_pct) OVER (PARTITION BY d.system_id ORDER BY d.day)) AS soh_daily_delta,
    d.equiv_full_cycles,
    (d.equiv_full_cycles - lag(d.equiv_full_cycles) OVER (PARTITION BY d.system_id ORDER BY d.day)) AS daily_equiv_cycles,
    d.daily_throughput_mwh,
    d.cum_charge_kwh,
    d.cum_discharge_kwh,
    d.avg_soc_pct,
    d.min_soc_pct,
    d.max_soc_pct,
    d.soc_swing_pct,
    d.hours_soc_gt90,
    d.hours_soc_lt15,
    d.avg_c_rate,
    d.max_c_rate,
    d.hours_c_rate_gt0_7,
    d.max_cell_voltage_v,
    d.min_cell_voltage_v,
    d.avg_imbalance_mv,
    d.max_imbalance_mv,
    d.avg_cell_temp_c,
    d.max_cell_temp_c,
    d.hours_temp_gt35,
    d.avg_ambient_c,
    d.sample_count
   FROM (d
     JOIN battery_master.battery_system s ON ((s.battery_system_id = d.system_id)));


--
-- Name: VIEW v_soh_daily_features; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON VIEW battery_telemetry.v_soh_daily_features IS 'Daily SOH training set: end-of-day SOH label + degradation-stress features per system.';


--
-- Name: v_soh_features_5min; Type: VIEW; Schema: battery_telemetry; Owner: -
--

CREATE VIEW battery_telemetry.v_soh_features_5min AS
 SELECT system_id,
    ts,
    soh_pct AS soh_label,
    soc_bms_pct AS soc_pct,
    c_rate,
    pack_voltage_v,
    pack_current_a,
    power_kw,
    cell_v_avg_v,
    cell_v_min_v,
    cell_v_max_v,
    cell_v_delta_mv,
    cell_temp_avg_c,
    cell_temp_min_c,
    cell_temp_max_c,
    (cell_temp_max_c - cell_temp_min_c) AS cell_temp_spread_c,
    coolant_temp_c,
    ambient_temp_c,
    equiv_full_cycles,
    cum_charge_kwh,
    cum_discharge_kwh
   FROM battery_telemetry.system_telemetry;


--
-- Name: VIEW v_soh_features_5min; Type: COMMENT; Schema: battery_telemetry; Owner: -
--

COMMENT ON VIEW battery_telemetry.v_soh_features_5min IS 'Per-sample BMS features + SOH label for real-time SOH inference.';


--
-- Name: weather_station; Type: TABLE; Schema: battery_telemetry; Owner: -
--

CREATE TABLE battery_telemetry.weather_station (
    station_id bigint NOT NULL,
    station_code text
);


--
-- Name: weather_station_station_id_seq; Type: SEQUENCE; Schema: battery_telemetry; Owner: -
--

ALTER TABLE battery_telemetry.weather_station ALTER COLUMN station_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_telemetry.weather_station_station_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: alarm_event alarm_event_pkey; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.alarm_event
    ADD CONSTRAINT alarm_event_pkey PRIMARY KEY (alarm_id, "time");


--
-- Name: calendar_day calendar_day_pkey; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.calendar_day
    ADD CONSTRAINT calendar_day_pkey PRIMARY KEY (calendar_date);


--
-- Name: dispatch_event dispatch_event_pkey; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.dispatch_event
    ADD CONSTRAINT dispatch_event_pkey PRIMARY KEY (dispatch_id, "time");


--
-- Name: metering_point metering_point_mp_code_key; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.metering_point
    ADD CONSTRAINT metering_point_mp_code_key UNIQUE (mp_code);


--
-- Name: metering_point metering_point_pkey; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.metering_point
    ADD CONSTRAINT metering_point_pkey PRIMARY KEY (metering_point_id);


--
-- Name: demand_telemetry pk_demand_telemetry; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.demand_telemetry
    ADD CONSTRAINT pk_demand_telemetry PRIMARY KEY (metering_point_id, ts);


--
-- Name: ems_telemetry pk_ems_telemetry; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.ems_telemetry
    ADD CONSTRAINT pk_ems_telemetry PRIMARY KEY (ems_id, ts);


--
-- Name: hvac_telemetry pk_hvac_telemetry; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.hvac_telemetry
    ADD CONSTRAINT pk_hvac_telemetry PRIMARY KEY (hvac_id, ts);


--
-- Name: module_telemetry pk_module_telemetry; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.module_telemetry
    ADD CONSTRAINT pk_module_telemetry PRIMARY KEY (module_id, ts);


--
-- Name: pcs_telemetry pk_pcs_telemetry; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.pcs_telemetry
    ADD CONSTRAINT pk_pcs_telemetry PRIMARY KEY (pcs_id, ts);


--
-- Name: system_telemetry pk_system_telemetry; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.system_telemetry
    ADD CONSTRAINT pk_system_telemetry PRIMARY KEY (system_id, ts);


--
-- Name: weather_actual pk_weather_actual; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.weather_actual
    ADD CONSTRAINT pk_weather_actual PRIMARY KEY (station_id, ts);


--
-- Name: weather_forecast pk_weather_forecast; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.weather_forecast
    ADD CONSTRAINT pk_weather_forecast PRIMARY KEY (station_id, issued_at, valid_at);


--
-- Name: weather_station weather_station_pkey; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.weather_station
    ADD CONSTRAINT weather_station_pkey PRIMARY KEY (station_id);


--
-- Name: weather_station weather_station_station_code_key; Type: CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.weather_station
    ADD CONSTRAINT weather_station_station_code_key UNIQUE (station_code);


--
-- Name: alarm_event_time_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX alarm_event_time_idx ON battery_telemetry.alarm_event USING btree ("time" DESC);


--
-- Name: demand_telemetry_ts_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX demand_telemetry_ts_idx ON battery_telemetry.demand_telemetry USING btree (ts DESC);


--
-- Name: dispatch_event_time_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX dispatch_event_time_idx ON battery_telemetry.dispatch_event USING btree ("time" DESC);


--
-- Name: ems_telemetry_ts_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX ems_telemetry_ts_idx ON battery_telemetry.ems_telemetry USING btree (ts DESC);


--
-- Name: hvac_telemetry_ts_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX hvac_telemetry_ts_idx ON battery_telemetry.hvac_telemetry USING btree (ts DESC);


--
-- Name: idx_alarm_event_active; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX idx_alarm_event_active ON battery_telemetry.alarm_event USING btree ("time" DESC) WHERE (end_time IS NULL);


--
-- Name: idx_alarm_event_catalog_time; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX idx_alarm_event_catalog_time ON battery_telemetry.alarm_event USING btree (alarm_catalog_id, "time" DESC);


--
-- Name: idx_alarm_event_system_time; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX idx_alarm_event_system_time ON battery_telemetry.alarm_event USING btree (battery_system_id, "time" DESC);


--
-- Name: idx_dispatch_event_ems_time; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX idx_dispatch_event_ems_time ON battery_telemetry.dispatch_event USING btree (ems_id, "time" DESC);


--
-- Name: idx_dispatch_event_mode_time; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX idx_dispatch_event_mode_time ON battery_telemetry.dispatch_event USING btree (dispatch_mode, "time" DESC);


--
-- Name: idx_dispatch_event_system_time; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX idx_dispatch_event_system_time ON battery_telemetry.dispatch_event USING btree (battery_system_id, "time" DESC);


--
-- Name: ix_demand_mp_ts; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX ix_demand_mp_ts ON battery_telemetry.demand_telemetry USING btree (metering_point_id, ts DESC);


--
-- Name: ix_ems_tel_ems_ts; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX ix_ems_tel_ems_ts ON battery_telemetry.ems_telemetry USING btree (ems_id, ts DESC);


--
-- Name: ix_hvac_tel_unit_ts; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX ix_hvac_tel_unit_ts ON battery_telemetry.hvac_telemetry USING btree (hvac_id, ts DESC);


--
-- Name: ix_mod_tel_module_ts; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX ix_mod_tel_module_ts ON battery_telemetry.module_telemetry USING btree (module_id, ts DESC);


--
-- Name: ix_pcs_tel_unit_ts; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX ix_pcs_tel_unit_ts ON battery_telemetry.pcs_telemetry USING btree (pcs_id, ts DESC);


--
-- Name: ix_sys_tel_system_ts; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX ix_sys_tel_system_ts ON battery_telemetry.system_telemetry USING btree (system_id, ts DESC);


--
-- Name: ix_wxfc_issued; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX ix_wxfc_issued ON battery_telemetry.weather_forecast USING btree (station_id, issued_at DESC, valid_at);


--
-- Name: module_telemetry_ts_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX module_telemetry_ts_idx ON battery_telemetry.module_telemetry USING btree (ts DESC);


--
-- Name: pcs_telemetry_ts_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX pcs_telemetry_ts_idx ON battery_telemetry.pcs_telemetry USING btree (ts DESC);


--
-- Name: system_telemetry_ts_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX system_telemetry_ts_idx ON battery_telemetry.system_telemetry USING btree (ts DESC);


--
-- Name: weather_actual_ts_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX weather_actual_ts_idx ON battery_telemetry.weather_actual USING btree (ts DESC);


--
-- Name: weather_forecast_valid_at_idx; Type: INDEX; Schema: battery_telemetry; Owner: -
--

CREATE INDEX weather_forecast_valid_at_idx ON battery_telemetry.weather_forecast USING btree (valid_at DESC);


--
-- Name: alarm_event alarm_event_alarm_catalog_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.alarm_event
    ADD CONSTRAINT alarm_event_alarm_catalog_id_fkey FOREIGN KEY (alarm_catalog_id) REFERENCES battery_master.alarm_catalog(alarm_catalog_id);


--
-- Name: alarm_event alarm_event_battery_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.alarm_event
    ADD CONSTRAINT alarm_event_battery_system_id_fkey FOREIGN KEY (battery_system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE SET NULL;


--
-- Name: alarm_event alarm_event_severity_level_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.alarm_event
    ADD CONSTRAINT alarm_event_severity_level_fkey FOREIGN KEY (severity_level) REFERENCES battery_master.alarm_severity(severity_level);


--
-- Name: demand_telemetry demand_telemetry_metering_point_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.demand_telemetry
    ADD CONSTRAINT demand_telemetry_metering_point_id_fkey FOREIGN KEY (metering_point_id) REFERENCES battery_master.metering_point(metering_point_id);


--
-- Name: dispatch_event dispatch_event_dispatch_mode_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.dispatch_event
    ADD CONSTRAINT dispatch_event_dispatch_mode_fkey FOREIGN KEY (dispatch_mode) REFERENCES battery_master.ems_dispatch_mode(mode_code);


--
-- Name: dispatch_event dispatch_event_ems_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.dispatch_event
    ADD CONSTRAINT dispatch_event_ems_id_fkey FOREIGN KEY (ems_id) REFERENCES battery_master.ems_controller(ems_id);


--
-- Name: dispatch_event dispatch_event_grid_service_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.dispatch_event
    ADD CONSTRAINT dispatch_event_grid_service_fkey FOREIGN KEY (grid_service) REFERENCES battery_master.ems_grid_service(service_code);


--
-- Name: dispatch_event dispatch_event_system_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.dispatch_event
    ADD CONSTRAINT dispatch_event_system_fkey FOREIGN KEY (battery_system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE SET NULL;


--
-- Name: ems_telemetry ems_telemetry_dispatch_mode_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.ems_telemetry
    ADD CONSTRAINT ems_telemetry_dispatch_mode_fkey FOREIGN KEY (dispatch_mode) REFERENCES battery_master.ems_dispatch_mode(mode_code);


--
-- Name: ems_telemetry ems_telemetry_ems_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.ems_telemetry
    ADD CONSTRAINT ems_telemetry_ems_id_fkey FOREIGN KEY (ems_id) REFERENCES battery_master.ems_controller(ems_id);


--
-- Name: ems_telemetry ems_telemetry_grid_service_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.ems_telemetry
    ADD CONSTRAINT ems_telemetry_grid_service_fkey FOREIGN KEY (grid_service) REFERENCES battery_master.ems_grid_service(service_code);


--
-- Name: hvac_telemetry hvac_telemetry_cooling_mode_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.hvac_telemetry
    ADD CONSTRAINT hvac_telemetry_cooling_mode_fkey FOREIGN KEY (cooling_mode) REFERENCES battery_master.hvac_cooling_mode(mode_code);


--
-- Name: hvac_telemetry hvac_telemetry_hvac_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.hvac_telemetry
    ADD CONSTRAINT hvac_telemetry_hvac_id_fkey FOREIGN KEY (hvac_id) REFERENCES battery_master.hvac_unit(hvac_id);


--
-- Name: module_telemetry module_telemetry_module_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.module_telemetry
    ADD CONSTRAINT module_telemetry_module_id_fkey FOREIGN KEY (module_id) REFERENCES battery_master.battery_module(module_id);


--
-- Name: pcs_telemetry pcs_telemetry_breaker_state_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.pcs_telemetry
    ADD CONSTRAINT pcs_telemetry_breaker_state_fkey FOREIGN KEY (breaker_state) REFERENCES battery_master.pcs_breaker_state(state_code);


--
-- Name: pcs_telemetry pcs_telemetry_grid_service_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.pcs_telemetry
    ADD CONSTRAINT pcs_telemetry_grid_service_fkey FOREIGN KEY (grid_service) REFERENCES battery_master.pcs_grid_service(service_code);


--
-- Name: pcs_telemetry pcs_telemetry_mode_code_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.pcs_telemetry
    ADD CONSTRAINT pcs_telemetry_mode_code_fkey FOREIGN KEY (mode_code) REFERENCES battery_master.pcs_mode(mode_code);


--
-- Name: pcs_telemetry pcs_telemetry_pcs_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.pcs_telemetry
    ADD CONSTRAINT pcs_telemetry_pcs_id_fkey FOREIGN KEY (pcs_id) REFERENCES battery_master.pcs(pcs_id);


--
-- Name: system_telemetry system_telemetry_contactor_state_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.system_telemetry
    ADD CONSTRAINT system_telemetry_contactor_state_fkey FOREIGN KEY (contactor_state) REFERENCES battery_master.contactor_state(state_code);


--
-- Name: system_telemetry system_telemetry_mode_code_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.system_telemetry
    ADD CONSTRAINT system_telemetry_mode_code_fkey FOREIGN KEY (mode_code) REFERENCES battery_master.operating_mode(mode_code);


--
-- Name: system_telemetry system_telemetry_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.system_telemetry
    ADD CONSTRAINT system_telemetry_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id);


--
-- Name: weather_actual weather_actual_station_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.weather_actual
    ADD CONSTRAINT weather_actual_station_id_fkey FOREIGN KEY (station_id) REFERENCES battery_master.weather_station(station_id);


--
-- Name: weather_forecast weather_forecast_station_id_fkey; Type: FK CONSTRAINT; Schema: battery_telemetry; Owner: -
--

ALTER TABLE ONLY battery_telemetry.weather_forecast
    ADD CONSTRAINT weather_forecast_station_id_fkey FOREIGN KEY (station_id) REFERENCES battery_master.weather_station(station_id);


--
-- PostgreSQL database dump complete
--

\unrestrict ilBNdFvvXHcech06yvBnLBYLVm8FCwLiRD1xuWSdA8rMlo9axpfDzoSGHcHYTr0



-- ============================================================ TimescaleDB hypertables
SET search_path = public;
SELECT create_hypertable('"battery_telemetry"."alarm_event"', by_range('time', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_telemetry"."demand_telemetry"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_telemetry"."dispatch_event"', by_range('time', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_telemetry"."ems_telemetry"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_telemetry"."hvac_telemetry"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_telemetry"."module_telemetry"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_telemetry"."pcs_telemetry"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_telemetry"."system_telemetry"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_telemetry"."weather_actual"', by_range('ts', INTERVAL '30 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_telemetry"."weather_forecast"', by_range('valid_at', INTERVAL '30 days'), if_not_exists => TRUE);

-- ============================================================ continuous aggregates
SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."demand_daily"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT metering_point_id,
    public.time_bucket('1 day'::interval, ts) AS bucket,
    max(net_load_kw) AS peak_net_load_kw,
    min(net_load_kw) AS min_net_load_kw,
    avg(net_load_kw) AS avg_net_load_kw,
    max(gross_load_kw) AS peak_gross_load_kw,
    (sum(net_load_kw) * (5.0 / 60.0)) AS net_energy_kwh,
    (sum(gross_load_kw) * (5.0 / 60.0)) AS gross_energy_kwh,
    (sum(behind_meter_gen_kw) * (5.0 / 60.0)) AS pv_energy_kwh,
    count(*) AS sample_count
   FROM battery_telemetry.demand_telemetry
  GROUP BY metering_point_id, (public.time_bucket('1 day'::interval, ts))
WITH NO DATA;

SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."ems_aux_15m"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT ems_id,
    public.time_bucket('00:15:00'::interval, ts) AS bucket,
    avg(aux_load_kw) AS aux_avg_kw,
    max(aux_load_kw) AS aux_max_kw,
    count(*) AS n
   FROM battery_telemetry.ems_telemetry
  GROUP BY ems_id, (public.time_bucket('00:15:00'::interval, ts))
WITH NO DATA;

SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."ems_telemetry_daily"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT ems_id,
    public.time_bucket('1 day'::interval, ts) AS bucket,
    max(poi_active_power_kw) AS peak_import_kw,
    min(poi_active_power_kw) AS peak_export_kw,
    (sum(poi_active_power_kw) FILTER (WHERE (poi_active_power_kw > (0)::numeric)) * (5.0 / 60.0)) AS energy_import_kwh,
    ((- sum(poi_active_power_kw) FILTER (WHERE (poi_active_power_kw < (0)::numeric))) * (5.0 / 60.0)) AS energy_export_kwh,
    (sum(aux_load_kw) * (5.0 / 60.0)) AS aux_energy_kwh,
    avg(market_price_mwh) AS avg_price_mwh,
    max(market_price_mwh) AS max_price_mwh,
    avg(plant_soc_pct) AS avg_soc_pct,
    min(plant_soc_pct) AS min_soc_pct,
    max(plant_soc_pct) AS max_soc_pct,
    (avg(plant_available) * 100.0) AS availability_pct,
    ((count(*) FILTER (WHERE (dispatch_mode = 'FREQUENCY_REGULATION'::text)))::numeric * (5.0 / 60.0)) AS freq_reg_hours,
    ((count(*) FILTER (WHERE (grid_service = 'ARBITRAGE'::text)))::numeric * (5.0 / 60.0)) AS arbitrage_hours,
    public.last(revenue_cum_usd, ts) AS revenue_cum_eod,
    public.last(cum_import_kwh, ts) AS cum_import_eod,
    public.last(cum_export_kwh, ts) AS cum_export_eod,
    count(*) AS sample_count
   FROM battery_telemetry.ems_telemetry
  GROUP BY ems_id, (public.time_bucket('1 day'::interval, ts))
WITH NO DATA;

SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."hvac_telemetry_daily"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT hvac_id,
    public.time_bucket('1 day'::interval, ts) AS bucket,
    (sum(hvac_power_kw) * (5.0 / 60.0)) AS energy_kwh,
    max(hvac_power_kw) AS peak_power_kw,
    (sum(heat_rejected_kw) * (5.0 / 60.0)) AS heat_rejected_kwh,
    max(battery_heat_load_kw) AS max_heat_load_kw,
    avg(battery_heat_load_kw) AS avg_heat_load_kw,
    max(cooling_capacity_kw) AS max_cooling_kw,
    avg(cop) AS avg_cop,
    max(coolant_return_temp_c) AS max_return_temp_c,
    max(enclosure_temp_c) AS max_enclosure_temp_c,
    max(enclosure_humidity_pct) AS max_humidity_pct,
    avg(ambient_temp_c) AS avg_ambient_c,
    ((count(*) FILTER (WHERE (cooling_mode = 'COOLING'::text)))::numeric * (5.0 / 60.0)) AS cooling_hours,
    ((count(*) FILTER (WHERE (cooling_mode = 'FREE_COOLING'::text)))::numeric * (5.0 / 60.0)) AS free_cooling_hours,
    max(alarm_level) AS max_alarm_level,
    public.last(cum_energy_kwh, ts) AS energy_kwh_eod,
    public.last(compressor_runtime_h, ts) AS runtime_h_eod,
    count(*) AS sample_count
   FROM battery_telemetry.hvac_telemetry
  GROUP BY hvac_id, (public.time_bucket('1 day'::interval, ts))
WITH NO DATA;

SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."hvac_thermal_15m"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT hvac_id,
    public.time_bucket('00:15:00'::interval, ts) AS bucket,
    max(coolant_return_temp_c) AS coolant_return_max_c,
    avg(coolant_return_temp_c) AS coolant_return_avg_c,
    max(enclosure_temp_c) AS enclosure_max_c,
    avg(hvac_power_kw) AS hvac_power_kw,
    avg(compressor_speed_pct) AS compressor_pct,
    count(*) AS n
   FROM battery_telemetry.hvac_telemetry
  GROUP BY hvac_id, (public.time_bucket('00:15:00'::interval, ts))
WITH NO DATA;

SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."module_telemetry_daily"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT module_id,
    public.time_bucket('1 day'::interval, ts) AS bucket,
    avg(cell_v_avg_v) AS avg_cell_v,
    min(cell_v_min_v) AS min_cell_v,
    max(cell_v_max_v) AS max_cell_v,
    (max(cell_v_max_v) - min(cell_v_min_v)) AS v_spread_v,
    ((max(cell_v_max_v) - min(cell_v_min_v)) * 1000.0) AS max_imbalance_mv,
    max(cell_temp_max_c) AS max_cell_temp_c,
    min(cell_temp_min_c) AS min_cell_temp_c,
    ((count(*) FILTER (WHERE balancing_active))::numeric * (5.0 / 60.0)) AS balancing_hours,
    count(*) AS sample_count
   FROM battery_telemetry.module_telemetry
  GROUP BY module_id, (public.time_bucket('1 day'::interval, ts))
WITH NO DATA;

SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."pcs_telemetry_daily"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT pcs_id,
    public.time_bucket('1 day'::interval, ts) AS bucket,
    max(ac_active_power_kw) AS peak_charge_kw,
    min(ac_active_power_kw) AS peak_discharge_kw,
    avg(ac_apparent_power_kva) AS avg_apparent_kva,
    max(ac_apparent_power_kva) AS peak_apparent_kva,
    min(power_factor) AS min_power_factor,
    max(ac_reactive_power_kvar) AS max_reactive_kvar,
    avg(efficiency_pct) AS avg_efficiency_pct,
    max(igbt_temp_c) AS max_igbt_temp_c,
    max(alarm_level) AS max_alarm_level,
    public.last(ac_energy_import_kwh, ts) AS cum_import_kwh_eod,
    public.last(ac_energy_export_kwh, ts) AS cum_export_kwh_eod,
    (sum(ac_active_power_kw) FILTER (WHERE (ac_active_power_kw > (0)::numeric)) * (5.0 / 60.0)) AS energy_import_kwh,
    ((- sum(ac_active_power_kw) FILTER (WHERE (ac_active_power_kw < (0)::numeric))) * (5.0 / 60.0)) AS energy_export_kwh,
    count(*) AS sample_count
   FROM battery_telemetry.pcs_telemetry
  GROUP BY pcs_id, (public.time_bucket('1 day'::interval, ts))
WITH NO DATA;

SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."pcs_thermal_15m"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT pcs_id,
    public.time_bucket('00:15:00'::interval, ts) AS bucket,
    max(igbt_temp_c) AS igbt_max_c,
    avg(igbt_temp_c) AS igbt_avg_c,
    max(heatsink_temp_c) AS heatsink_max_c,
    avg(abs(ac_active_power_kw)) AS ac_abs_kw,
    avg(ac_apparent_power_kva) AS apparent_kva,
    count(*) AS n
   FROM battery_telemetry.pcs_telemetry
  GROUP BY pcs_id, (public.time_bucket('00:15:00'::interval, ts))
WITH NO DATA;

SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."system_telemetry_daily"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT system_id,
    public.time_bucket('1 day'::interval, ts) AS bucket,
    min(soc_bms_pct) AS min_soc_pct,
    max(soc_bms_pct) AS max_soc_pct,
    avg(soc_bms_pct) AS avg_soc_pct,
    min(pack_voltage_v) AS min_pack_voltage_v,
    max(pack_voltage_v) AS max_pack_voltage_v,
    avg(power_kw) AS avg_power_kw,
    max(cell_temp_max_c) AS max_cell_temp_c,
    max(cell_v_delta_mv) AS max_cell_delta_mv,
    max(alarm_level) AS max_alarm_level,
    public.last(soh_pct, ts) AS soh_pct_eod,
    public.last(cum_charge_kwh, ts) AS cum_charge_kwh_eod,
    public.last(cum_discharge_kwh, ts) AS cum_discharge_kwh_eod,
    public.last(equiv_full_cycles, ts) AS equiv_full_cycles_eod,
    (sum(power_kw) FILTER (WHERE (power_kw > (0)::numeric)) * (5.0 / 60.0)) AS energy_charged_kwh,
    ((- sum(power_kw) FILTER (WHERE (power_kw < (0)::numeric))) * (5.0 / 60.0)) AS energy_discharged_kwh,
    count(*) AS sample_count
   FROM battery_telemetry.system_telemetry
  GROUP BY system_id, (public.time_bucket('1 day'::interval, ts))
WITH NO DATA;

SET search_path = "battery_telemetry", public;
CREATE MATERIALIZED VIEW "battery_telemetry"."system_thermal_15m"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT system_id,
    public.time_bucket('00:15:00'::interval, ts) AS bucket,
    max(cell_temp_max_c) AS cell_max_c,
    avg(cell_temp_max_c) AS cell_max_avg_c,
    avg(abs(power_kw)) AS power_abs_kw,
    avg(abs(c_rate)) AS c_rate_abs,
    avg(ambient_temp_c) AS ambient_c,
    count(*) AS n
   FROM battery_telemetry.system_telemetry
  GROUP BY system_id, (public.time_bucket('00:15:00'::interval, ts))
WITH NO DATA;

SET search_path = public;

-- ============================================================ views on continuous aggregates
CREATE OR REPLACE VIEW "battery_telemetry"."v_aux_rolling" AS
SELECT x.ems_id,
    x.bucket,
    avg(x.aux_avg_kw) OVER w1 AS aux_1h_kw,
    max(x.aux_max_kw) OVER w1 AS aux_max_1h_kw,
    avg(x.aux_avg_kw) OVER w3 AS aux_3h_kw,
    avg(h.hvac_power_kw) OVER w1 AS hvac_1h_kw
   FROM battery_telemetry.ems_aux_15m x
     JOIN battery_master.ems_controller ec ON ec.ems_id = x.ems_id
     LEFT JOIN battery_master.v_thermal_assets a ON a.battery_system_id = ec.battery_system_id
     LEFT JOIN battery_telemetry.hvac_thermal_15m h ON h.hvac_id = a.hvac_id AND h.bucket = x.bucket
  WINDOW w1 AS (PARTITION BY x.ems_id ORDER BY x.bucket ROWS BETWEEN 3 PRECEDING AND CURRENT ROW), w3 AS (PARTITION BY x.ems_id ORDER BY x.bucket ROWS BETWEEN 11 PRECEDING AND CURRENT ROW);

CREATE OR REPLACE VIEW "battery_telemetry"."v_thermal_rolling_1h" AS
SELECT a.battery_system_id,
    s.bucket,
    max(s.cell_max_c) OVER w AS cell_max_1h_c,
    avg(s.power_abs_kw) OVER w AS power_abs_1h_kw,
    avg(s.c_rate_abs) OVER w AS c_rate_abs_1h,
    max(p.igbt_max_c) OVER w AS igbt_max_1h_c,
    avg(p.apparent_kva) OVER w AS apparent_1h_kva,
    max(h.coolant_return_max_c) OVER w AS coolant_return_max_1h_c,
    max(h.enclosure_max_c) OVER w AS enclosure_max_1h_c,
    avg(h.hvac_power_kw) OVER w AS hvac_power_1h_kw
   FROM battery_master.v_thermal_assets a
     JOIN battery_telemetry.system_thermal_15m s ON s.system_id = a.battery_system_id
     LEFT JOIN battery_telemetry.pcs_thermal_15m p ON p.pcs_id = a.pcs_id AND p.bucket = s.bucket
     LEFT JOIN battery_telemetry.hvac_thermal_15m h ON h.hvac_id = a.hvac_id AND h.bucket = s.bucket
  WINDOW w AS (PARTITION BY a.battery_system_id ORDER BY s.bucket ROWS BETWEEN 3 PRECEDING AND CURRENT ROW);

CREATE OR REPLACE VIEW "battery_telemetry"."v_aux_features" AS
SELECT e.ts,
    e.ems_id,
    bs.site_id,
    ec.battery_system_id,
    a.pcs_id,
    a.hvac_id,
    ( SELECT min(w.station_id) AS min
           FROM battery_master.weather_station w
          WHERE w.site_id = bs.site_id) AS station_id,
    e.aux_load_kw,
    e.aux_load_pct,
    e.p_setpoint_kw,
    e.dispatch_mode,
    e.grid_service,
    h.hvac_power_kw,
    h.cooling_mode,
    h.cop,
    h.coolant_setpoint_c,
    h.compressor_speed_pct,
    h.condenser_fan_pct,
    h.coolant_return_temp_c,
    h.enclosure_temp_c,
    h.enclosure_humidity_pct,
    h.battery_heat_load_kw,
    h.cooling_capacity_kw,
    COALESCE(h.ambient_temp_c, s.ambient_temp_c) AS ambient_temp_c,
    s.power_kw,
    s.c_rate,
    s.cell_temp_max_c,
    p.ac_apparent_power_kva,
    r.aux_1h_kw,
    r.aux_max_1h_kw,
    r.aux_3h_kw,
    r.hvac_1h_kw
   FROM battery_telemetry.ems_telemetry e
     JOIN battery_master.ems_controller ec ON ec.ems_id = e.ems_id
     JOIN battery_master.battery_system bs ON bs.battery_system_id = ec.battery_system_id
     LEFT JOIN battery_master.v_thermal_assets a ON a.battery_system_id = ec.battery_system_id
     LEFT JOIN battery_telemetry.hvac_telemetry h ON h.hvac_id = a.hvac_id AND h.ts = e.ts
     LEFT JOIN battery_telemetry.system_telemetry s ON s.system_id = ec.battery_system_id AND s.ts = e.ts
     LEFT JOIN battery_telemetry.pcs_telemetry p ON p.pcs_id = a.pcs_id AND p.ts = e.ts
     LEFT JOIN battery_telemetry.v_aux_rolling r ON r.ems_id = e.ems_id AND r.bucket = (public.time_bucket('00:15:00'::interval, e.ts) - '00:15:00'::interval);

CREATE OR REPLACE VIEW "battery_telemetry"."v_thermal_features" AS
SELECT s.ts,
    a.battery_system_id,
    a.pcs_id,
    a.hvac_id,
    a.ems_id,
    s.cell_temp_max_c,
    s.cell_temp_avg_c,
    s.cell_temp_min_c,
    s.power_kw,
    s.c_rate,
    s.soc_bms_pct AS soc_pct,
    s.ambient_temp_c,
    s.coolant_temp_c AS bms_coolant_temp_c,
    p.igbt_temp_c,
    p.heatsink_temp_c,
    p.inlet_coolant_temp_c,
    p.ac_active_power_kw,
    p.ac_apparent_power_kva,
    p.dc_power_kw,
    p.mode_code AS pcs_mode,
    h.cooling_mode,
    h.compressor_speed_pct,
    h.coolant_flow_lpm,
    h.coolant_setpoint_c,
    h.coolant_supply_temp_c,
    h.coolant_return_temp_c,
    h.hvac_power_kw,
    h.enclosure_temp_c,
    h.battery_heat_load_kw,
    e.p_setpoint_kw,
    e.dispatch_mode,
    e.grid_service,
    r.cell_max_1h_c,
    r.power_abs_1h_kw,
    r.c_rate_abs_1h,
    r.igbt_max_1h_c,
    r.apparent_1h_kva,
    r.coolant_return_max_1h_c,
    r.enclosure_max_1h_c,
    r.hvac_power_1h_kw
   FROM battery_telemetry.system_telemetry s
     JOIN battery_master.v_thermal_assets a ON a.battery_system_id = s.system_id
     LEFT JOIN battery_telemetry.pcs_telemetry p ON p.pcs_id = a.pcs_id AND p.ts = s.ts
     LEFT JOIN battery_telemetry.hvac_telemetry h ON h.hvac_id = a.hvac_id AND h.ts = s.ts
     LEFT JOIN battery_telemetry.ems_telemetry e ON e.ems_id = a.ems_id AND e.ts = s.ts
     LEFT JOIN battery_telemetry.v_thermal_rolling_1h r ON r.battery_system_id = s.system_id AND r.bucket = (public.time_bucket('00:15:00'::interval, s.ts) - '00:15:00'::interval);

-- ============================================================ compression settings and policies
ALTER TABLE "battery_telemetry"."demand_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"metering_point_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."ems_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"ems_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."hvac_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"hvac_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."module_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"module_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."pcs_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"pcs_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."system_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"system_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."weather_actual" SET (timescaledb.compress, timescaledb.compress_segmentby = '"station_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
SELECT add_compression_policy('"battery_telemetry"."demand_telemetry"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."ems_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."hvac_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."module_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."pcs_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."system_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."weather_actual"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."demand_daily"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '01:00:00', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."ems_aux_15m"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '00:15:00', schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."ems_telemetry_daily"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '01:00:00', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."hvac_telemetry_daily"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '01:00:00', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."hvac_thermal_15m"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '00:15:00', schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."module_telemetry_daily"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '01:00:00', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."pcs_telemetry_daily"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '01:00:00', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."pcs_thermal_15m"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '00:15:00', schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."system_telemetry_daily"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '01:00:00', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_telemetry"."system_thermal_15m"', start_offset => INTERVAL '3 days', end_offset => INTERVAL '00:15:00', schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."demand_telemetry"', drop_after => INTERVAL '3 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."ems_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."hvac_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."module_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."pcs_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."system_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);

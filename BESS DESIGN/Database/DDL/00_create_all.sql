-- BESS database DDL: battery_master, battery_users, battery_raw, battery_telemetry, battery_ml, battery_itops
-- Generated 2026-10-22 by db_docs/generate_ddl.py from database Battery
-- Sections: extensions, pg_dump schema DDL, TimescaleDB hypertables + compression, continuous aggregates,
--           views on continuous aggregates, TimescaleDB policies

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================ schema DDL (pg_dump)
--
-- PostgreSQL database dump
--

\restrict V4Qqx9kMLZtwhCWEP9rKpwXFfWtGnxR0zFmG6gOJFw35ucW5nRsqwL0Ag1KLXOR

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
-- Name: battery_itops; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_itops;


--
-- Name: battery_master; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_master;


--
-- Name: battery_ml; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_ml;


--
-- Name: battery_raw; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_raw;


--
-- Name: battery_telemetry; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_telemetry;


--
-- Name: battery_users; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_users;


--
-- Name: tenant_status; Type: TYPE; Schema: battery_master; Owner: -
--

CREATE TYPE battery_master.tenant_status AS ENUM (
    'active',
    'suspended',
    'inactive'
);


--
-- Name: tenant_type; Type: TYPE; Schema: battery_master; Owner: -
--

CREATE TYPE battery_master.tenant_type AS ENUM (
    'Utility',
    'IPP',
    'C&I',
    'Developer',
    'Aggregator / VPP',
    'Government',
    'Other'
);


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
-- Name: dispatch_outcome; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.dispatch_outcome (
    system_id bigint NOT NULL,
    interval_start timestamp with time zone NOT NULL,
    run_id bigint,
    p_scheduled_kw numeric(10,2),
    p_actual_kw numeric(10,2),
    price_mwh numeric(10,2),
    energy_mwh numeric(12,6),
    gross_revenue_usd numeric(12,4),
    degradation_cost_usd numeric(12,4),
    grid_cost_usd numeric(12,4),
    net_pnl_usd numeric(12,4)
);


--
-- Name: TABLE dispatch_outcome; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.dispatch_outcome IS 'Realized per-interval P&L: scheduled vs actual power, revenue net of cycling + grid cost (training label / scoring).';


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
-- Name: mv_anomaly_score; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.mv_anomaly_score (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    split text NOT NULL,
    regime text,
    anomaly_score double precision,
    score_smooth double precision,
    model_flag boolean DEFAULT false NOT NULL,
    is_anomaly boolean DEFAULT false NOT NULL,
    rule_flags text[],
    model_scores jsonb,
    models_flagging smallint,
    top_contributors jsonb
);


--
-- Name: TABLE mv_anomaly_score; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.mv_anomaly_score IS 'Per-interval multivariate anomaly score, flag and top contributing features (sibling of system_telemetry).';


--
-- Name: dam_price; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.dam_price (
    node_id bigint NOT NULL,
    delivery_start timestamp with time zone NOT NULL,
    block_minutes smallint DEFAULT 60 NOT NULL,
    price_mwh numeric(10,2) NOT NULL,
    cleared_mw numeric(10,2)
);


--
-- Name: TABLE dam_price; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.dam_price IS 'Day-ahead market cleared energy prices per delivery block.';


--
-- Name: rt_price; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.rt_price (
    node_id bigint NOT NULL,
    interval_start timestamp with time zone NOT NULL,
    block_minutes smallint DEFAULT 15 NOT NULL,
    price_mwh numeric(10,2) NOT NULL
);


--
-- Name: TABLE rt_price; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.rt_price IS 'Real-time / imbalance settlement prices (what intraday deviations settle at).';


--
-- Name: price_forecast; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.price_forecast (
    node_id bigint NOT NULL,
    issued_at timestamp with time zone NOT NULL,
    target_ts timestamp with time zone NOT NULL,
    horizon_h numeric(6,2),
    p10_mwh numeric(10,2),
    p50_mwh numeric(10,2) NOT NULL,
    p90_mwh numeric(10,2),
    model text
);


--
-- Name: TABLE price_forecast; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.price_forecast IS 'Probabilistic price forecast (quantiles) per issue vintage; horizon widens the band.';


--
-- Name: price_scenario; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.price_scenario (
    node_id bigint NOT NULL,
    issued_at timestamp with time zone NOT NULL,
    scenario_id smallint NOT NULL,
    target_ts timestamp with time zone NOT NULL,
    price_mwh numeric(10,2) NOT NULL,
    probability numeric(6,4)
);


--
-- Name: TABLE price_scenario; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.price_scenario IS 'Sampled price paths + weights for stochastic/robust dispatch optimization.';


--
-- Name: as_price; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.as_price (
    product_id bigint NOT NULL,
    delivery_start timestamp with time zone NOT NULL,
    block_minutes smallint DEFAULT 60 NOT NULL,
    capacity_price_mw numeric(10,2),
    performance_price numeric(10,2)
);


--
-- Name: TABLE as_price; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.as_price IS 'Ancillary-service capacity/performance clearing prices per block.';


--
-- Name: dispatch_schedule; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.dispatch_schedule (
    run_id bigint NOT NULL,
    interval_start timestamp with time zone NOT NULL,
    p_setpoint_kw numeric(10,2) NOT NULL,
    soc_target_pct numeric(5,2),
    mode text,
    market text,
    forecast_price_mwh numeric(10,2)
);


--
-- Name: TABLE dispatch_schedule; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.dispatch_schedule IS 'Optimizer-produced setpoint schedule per interval (the decision to execute).';


--
-- Name: loss_ledger; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.loss_ledger (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    direction text NOT NULL,
    p_poi_kw numeric(10,3),
    p_ac_kw numeric(10,3),
    p_dc_kw numeric(10,3),
    p_term_kw numeric(10,3),
    p_chem_kw numeric(10,3),
    load_frac numeric(8,5),
    loss_batt_kwh numeric(10,5),
    loss_dc_kwh numeric(10,5),
    loss_pcs_kwh numeric(10,5),
    loss_xfmr_kwh numeric(10,5),
    aux_hvac_kwh numeric(10,5),
    aux_ctrl_kwh numeric(10,5),
    standby_kwh numeric(10,5),
    exp_batt_kwh numeric(10,5),
    exp_pcs_kwh numeric(10,5),
    exp_xfmr_kwh numeric(10,5),
    exp_aux_kwh numeric(10,5),
    eta_pcs numeric(8,5),
    eta_batt numeric(8,5),
    closure_kwh numeric(10,5),
    price_mwh numeric(10,3),
    CONSTRAINT loss_ledger_direction_check CHECK ((direction = ANY (ARRAY['CHARGE'::text, 'DISCHARGE'::text, 'IDLE'::text])))
);


--
-- Name: heatload_ledger; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.heatload_ledger (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    direction text NOT NULL,
    is_train boolean NOT NULL,
    q_batt_irr_kw numeric(10,4),
    q_batt_rev_kw numeric(10,4),
    q_pcs_kw numeric(10,4),
    q_aux_kw numeric(10,4),
    q_solar_kw numeric(10,4),
    q_env_kw numeric(10,4),
    q_storage_kw numeric(10,4),
    q_total_kw numeric(10,4),
    q_model_kw numeric(10,4),
    measured_kw numeric(10,4),
    heat_load_sensor_kw numeric(10,4),
    cooling_kw numeric(10,4),
    hvac_kw numeric(10,4),
    residual_kw numeric(10,4),
    t_amb_c numeric(7,3),
    t_enc_c numeric(7,3),
    t_cell_max_c numeric(7,3),
    dt_cell_c numeric(7,3),
    ghi_wm2 numeric(8,2),
    ghi_source text,
    CONSTRAINT heatload_ledger_direction_check CHECK ((direction = ANY (ARRAY['CHARGE'::text, 'DISCHARGE'::text, 'IDLE'::text])))
);


--
-- Name: heatload_forecast_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.heatload_forecast_point (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    issued_at timestamp with time zone NOT NULL,
    horizon_min integer NOT NULL,
    valid_at timestamp with time zone NOT NULL,
    actual_kw numeric(10,4),
    persistence_kw numeric(10,4),
    physics_kw numeric(10,4),
    p10_kw numeric(10,4),
    p50_kw numeric(10,4),
    p90_kw numeric(10,4),
    plan_kw numeric(10,3)
);


--
-- Name: hvac_cop_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.hvac_cop_point (
    run_id bigint NOT NULL,
    hvac_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    mode text,
    steady boolean NOT NULL,
    is_train boolean NOT NULL,
    cop_actual numeric(8,4),
    cop_logged numeric(8,4),
    cop_ratio numeric(8,4),
    cop_loop numeric(8,4),
    cop_map numeric(8,4),
    cop_grey numeric(8,4),
    cop_hybrid numeric(8,4),
    cop_expected numeric(8,4),
    cop_residual numeric(8,4),
    eta_2nd_law numeric(8,5),
    cop_carnot numeric(9,4),
    lift_k numeric(8,3),
    plr numeric(7,4),
    cap_actual_kw numeric(10,3),
    cap_expected_kw numeric(10,3),
    q_dt_kw numeric(10,3),
    power_kw numeric(10,3),
    power_expected_kw numeric(10,3),
    rej_closure_kw numeric(10,3),
    t_amb_c numeric(7,3),
    t_supply_c numeric(7,3)
);


--
-- Name: activity_log; Type: TABLE; Schema: battery_itops; Owner: -
--

CREATE TABLE battery_itops.activity_log (
    activity_id bigint NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    service text NOT NULL,
    kind text NOT NULL,
    event text NOT NULL,
    outcome text NOT NULL,
    request_id text,
    user_email text,
    role text,
    method text,
    path text,
    status_code smallint,
    duration_ms integer,
    operation text,
    rows_total integer,
    rows_inserted integer,
    rows_updated integer,
    rows_rejected integer,
    ip text,
    detail jsonb,
    CONSTRAINT activity_log_kind_check CHECK ((kind = ANY (ARRAY['REQUEST'::text, 'AUTH'::text, 'LOAD'::text, 'KPI'::text, 'TRAINING'::text, 'ERROR'::text]))),
    CONSTRAINT activity_log_outcome_check CHECK ((outcome = ANY (ARRAY['success'::text, 'failed'::text])))
);


--
-- Name: activity_log_activity_id_seq; Type: SEQUENCE; Schema: battery_itops; Owner: -
--

ALTER TABLE battery_itops.activity_log ALTER COLUMN activity_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_itops.activity_log_activity_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aging_snapshot; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.aging_snapshot (
    system_id bigint NOT NULL,
    snapshot_date date NOT NULL,
    age_days integer,
    calendar_age_years numeric(6,2),
    cum_throughput_mwh numeric(12,1),
    equiv_full_cycles numeric(10,1),
    avg_dod_pct numeric(5,1),
    avg_cell_temp_c numeric(5,1),
    days_at_high_soc numeric(6,1),
    soh_pct numeric(5,2),
    internal_resistance_mohm numeric(8,3),
    rul_cycles numeric(10,1),
    rul_days integer,
    is_censored boolean,
    eol_reached boolean
);


--
-- Name: TABLE aging_snapshot; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.aging_snapshot IS 'Monthly aging features + RUL labels (rul_days/rul_cycles); is_censored for survival models.';


--
-- Name: alarm_catalog; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.alarm_catalog (
    alarm_catalog_id bigint NOT NULL,
    alarm_code text NOT NULL,
    source text NOT NULL,
    alarm_type text NOT NULL,
    severity_level smallint NOT NULL,
    asset_type text,
    description text NOT NULL,
    probable_cause text,
    threshold numeric,
    unit text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT alarm_catalog_code_not_blank CHECK ((btrim(alarm_code) <> ''::text)),
    CONSTRAINT alarm_catalog_description_not_blank CHECK ((btrim(description) <> ''::text)),
    CONSTRAINT alarm_catalog_source_check CHECK ((source = ANY (ARRAY['BMS'::text, 'PCS'::text, 'HVAC'::text, 'EMS'::text]))),
    CONSTRAINT alarm_catalog_type_not_blank CHECK ((btrim(alarm_type) <> ''::text))
);


--
-- Name: TABLE alarm_catalog; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.alarm_catalog IS 'Alarm definitions per source system (BMS/PCS/HVAC/EMS); key (source, alarm_code)';


--
-- Name: COLUMN alarm_catalog.threshold; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON COLUMN battery_master.alarm_catalog.threshold IS 'Trip threshold, in unit; NULL for event-type alarms';


--
-- Name: alarm_catalog_alarm_catalog_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.alarm_catalog ALTER COLUMN alarm_catalog_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.alarm_catalog_alarm_catalog_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: alarm_severity; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.alarm_severity (
    severity_level smallint NOT NULL,
    severity_name text NOT NULL
);


--
-- Name: as_award; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.as_award (
    award_id bigint NOT NULL,
    system_id bigint NOT NULL,
    product_id bigint NOT NULL,
    delivery_start timestamp with time zone NOT NULL,
    delivery_end timestamp with time zone NOT NULL,
    awarded_mw numeric(8,3) NOT NULL,
    capacity_price_mw numeric(10,2),
    revenue_usd numeric(12,2),
    CONSTRAINT chk_as_award_window CHECK ((delivery_end > delivery_start))
);


--
-- Name: TABLE as_award; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.as_award IS 'Awarded AS commitments; each reserves power/energy headroom the optimizer must respect.';


--
-- Name: as_award_award_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.as_award ALTER COLUMN award_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.as_award_award_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: as_product; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.as_product (
    product_id bigint NOT NULL,
    market_id bigint NOT NULL,
    product_code text NOT NULL,
    name text NOT NULL,
    direction text,
    min_bid_mw numeric(8,3),
    sustain_minutes smallint,
    response_seconds smallint,
    settlement text,
    description text,
    CONSTRAINT as_product_direction_check CHECK ((direction = ANY (ARRAY['UP'::text, 'DOWN'::text, 'SYMMETRIC'::text]))),
    CONSTRAINT as_product_settlement_check CHECK ((settlement = ANY (ARRAY['CAPACITY'::text, 'ENERGY'::text, 'CAPACITY+PERFORMANCE'::text])))
);


--
-- Name: TABLE as_product; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.as_product IS 'Ancillary-service products the asset can bid (reg, reserves, capacity).';


--
-- Name: as_product_product_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.as_product ALTER COLUMN product_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.as_product_product_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: asset_hierarchy; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.asset_hierarchy (
    asset_type character varying(50) CONSTRAINT asset_asset_type_not_null NOT NULL,
    asset_name character varying(200),
    external_id character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    asset_id uuid DEFAULT gen_random_uuid() CONSTRAINT asset_asset_id_not_null NOT NULL,
    parent_asset_id uuid,
    source_id bigint NOT NULL
);


--
-- Name: battery_chemistry; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.battery_chemistry (
    chemistry_code text NOT NULL,
    description text NOT NULL,
    nominal_cell_v numeric(4,2) NOT NULL,
    min_cell_v numeric(4,2) NOT NULL,
    max_cell_v numeric(4,2) NOT NULL
);


--
-- Name: battery_container; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.battery_container (
    container_number character varying(50),
    manufacturer character varying(100),
    installation_date date,
    status character varying(20),
    container_id bigint NOT NULL,
    battery_system_id bigint NOT NULL,
    source_uuid uuid,
    container_type text,
    ip_rating text,
    fire_suppression text
);


--
-- Name: battery_container_container_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.battery_container ALTER COLUMN container_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME battery_master.battery_container_container_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: battery_module; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.battery_module (
    serial_number character varying(100),
    chemistry character varying(50),
    nominal_voltage numeric(10,2),
    capacity_ah numeric(10,2),
    manufacture_date date,
    installation_date date,
    status character varying(20),
    module_id bigint NOT NULL,
    pack_id bigint NOT NULL,
    source_uuid uuid,
    cell_count integer,
    soh_pct numeric(5,2),
    CONSTRAINT battery_module_cell_count_check CHECK (((cell_count IS NULL) OR (cell_count >= 0))),
    CONSTRAINT battery_module_soh_pct_check CHECK (((soh_pct IS NULL) OR ((soh_pct >= (0)::numeric) AND (soh_pct <= (100)::numeric))))
);


--
-- Name: battery_module_module_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.battery_module ALTER COLUMN module_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME battery_master.battery_module_module_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: battery_opt_param; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.battery_opt_param (
    param_id bigint NOT NULL,
    system_id bigint NOT NULL,
    valid_from date NOT NULL,
    usable_energy_mwh numeric(10,3) NOT NULL,
    soc_min_pct numeric(5,2) NOT NULL,
    soc_max_pct numeric(5,2) NOT NULL,
    p_charge_max_kw numeric(10,2) NOT NULL,
    p_discharge_max_kw numeric(10,2) NOT NULL,
    ramp_kw_per_min numeric(10,2),
    rte_ac numeric(6,4),
    self_discharge_pct_day numeric(6,4),
    max_cycles_per_day numeric(5,2),
    min_dwell_min smallint,
    degradation_cost_mwh numeric(10,3),
    aux_load_kw numeric(10,2),
    CONSTRAINT chk_soc_band CHECK ((soc_min_pct < soc_max_pct))
);


--
-- Name: TABLE battery_opt_param; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.battery_opt_param IS 'Per-system optimizer parameters: usable energy, SOC band, power/ramp limits, RTE, cycle cap, degradation cost.';


--
-- Name: battery_opt_param_param_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.battery_opt_param ALTER COLUMN param_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.battery_opt_param_param_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: battery_pack; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.battery_pack (
    pack_number character varying(50),
    nominal_voltage numeric(10,2),
    nominal_capacity_ah numeric(10,2),
    status character varying(20),
    pack_id bigint NOT NULL,
    container_id bigint NOT NULL,
    source_uuid uuid,
    module_count integer,
    CONSTRAINT battery_pack_module_count_check CHECK (((module_count IS NULL) OR (module_count >= 0)))
);


--
-- Name: battery_pack_pack_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.battery_pack ALTER COLUMN pack_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME battery_master.battery_pack_pack_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: battery_provenance; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.battery_provenance (
    system_id bigint NOT NULL,
    manufacturer text,
    cell_model text,
    chemistry text NOT NULL,
    batch_lot text,
    cell_format text,
    build_date date,
    nameplate_kwh numeric(10,2),
    bol_capacity_kwh numeric(10,2),
    bol_resistance_mohm numeric(8,3),
    usage_cycles_per_day numeric(5,2),
    climate_avg_temp_c numeric(5,2)
);


--
-- Name: TABLE battery_provenance; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.battery_provenance IS 'Cell provenance, batch, and BOL baseline per system.';


--
-- Name: battery_system; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.battery_system (
    system_name character varying(100) NOT NULL,
    manufacturer character varying(100),
    model character varying(100),
    rated_power_mw numeric(10,2),
    rated_energy_mwh numeric(10,2),
    nominal_dc_voltage numeric(10,2),
    status character varying(20),
    created_at timestamp with time zone DEFAULT now(),
    chemistry_code text NOT NULL,
    series_cells integer NOT NULL,
    parallel_cells integer NOT NULL,
    commissioned_on date,
    bms_firmware text,
    battery_system_id bigint NOT NULL,
    site_id bigint NOT NULL,
    source_uuid uuid
);


--
-- Name: battery_system_battery_system_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.battery_system ALTER COLUMN battery_system_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME battery_master.battery_system_battery_system_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: calendar_day; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.calendar_day (
    calendar_date date NOT NULL,
    day_of_week text NOT NULL,
    is_weekend boolean NOT NULL,
    is_holiday boolean DEFAULT false NOT NULL,
    holiday_name text,
    day_type text NOT NULL,
    CONSTRAINT calendar_day_day_type_check CHECK ((day_type = ANY (ARRAY['Weekday'::text, 'Weekend'::text, 'Holiday'::text])))
);


--
-- Name: TABLE calendar_day; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.calendar_day IS 'Daily calendar with holiday/day-type flags.';


--
-- Name: capacity_test; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.capacity_test (
    test_id bigint NOT NULL,
    system_id bigint NOT NULL,
    test_date date NOT NULL,
    age_days integer,
    equiv_full_cycles numeric(10,1),
    measured_capacity_kwh numeric(10,2),
    soh_pct numeric(5,2),
    internal_resistance_mohm numeric(8,3),
    test_temp_c numeric(5,2),
    method text,
    CONSTRAINT chk_rpt_soh CHECK (((soh_pct IS NULL) OR ((soh_pct >= (0)::numeric) AND (soh_pct <= (110)::numeric))))
);


--
-- Name: TABLE capacity_test; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.capacity_test IS 'Periodic RPT capacity/resistance checkpoints (the SOH ground truth).';


--
-- Name: capacity_test_test_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.capacity_test ALTER COLUMN test_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.capacity_test_test_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: contactor_state; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.contactor_state (
    state_code text NOT NULL,
    description text
);


--
-- Name: current_sensor_cal; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.current_sensor_cal (
    system_id bigint NOT NULL,
    calibrated_on date NOT NULL,
    offset_a numeric(7,3),
    gain_error_pct numeric(6,3),
    drift_a_per_day numeric(7,4)
);


--
-- Name: decision_state; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.decision_state (
    run_id bigint NOT NULL,
    soc_start_pct numeric(5,2) NOT NULL,
    soh_pct numeric(5,2),
    usable_energy_mwh numeric(10,3),
    avg_cell_temp_c numeric(5,1),
    p_charge_avail_kw numeric(10,2),
    p_discharge_avail_kw numeric(10,2),
    cycles_used_today numeric(5,2),
    aux_load_forecast_kw numeric(10,2),
    reserved_mw_as numeric(8,3)
);


--
-- Name: TABLE decision_state; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.decision_state IS 'State the optimizer saw at horizon start (SOC/SOH/temp/available power/cycle budget/AS reservation).';


--
-- Name: degradation_cost_curve; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.degradation_cost_curve (
    system_id bigint NOT NULL,
    dod_band_pct smallint NOT NULL,
    marginal_cost_mwh numeric(10,3) NOT NULL,
    basis text
);


--
-- Name: TABLE degradation_cost_curve; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.degradation_cost_curve IS 'Marginal $/MWh cycling cost by depth-of-discharge band; deeper cycles cost more (from RUL aging economics).';


--
-- Name: demand_tariff; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.demand_tariff (
    tariff_id bigint NOT NULL,
    site_id bigint NOT NULL,
    name text NOT NULL,
    demand_charge_per_kw numeric(10,2),
    peak_window_start numeric(4,2),
    peak_window_end numeric(4,2),
    measurement_minutes smallint DEFAULT 15,
    ratchet_pct numeric(5,2),
    valid_from date,
    CONSTRAINT chk_tariff_window CHECK (((peak_window_start IS NULL) OR (peak_window_end IS NULL) OR (peak_window_start < peak_window_end)))
);


--
-- Name: TABLE demand_tariff; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.demand_tariff IS 'Demand-charge definition; sets what "peak" means economically.';


--
-- Name: demand_tariff_tariff_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.demand_tariff ALTER COLUMN tariff_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.demand_tariff_tariff_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: efficiency_curve; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.efficiency_curve (
    system_id bigint NOT NULL,
    direction text NOT NULL,
    power_fraction numeric(5,3) NOT NULL,
    soc_band text NOT NULL,
    one_way_eff numeric(6,4) NOT NULL,
    CONSTRAINT efficiency_curve_direction_check CHECK ((direction = ANY (ARRAY['CHARGE'::text, 'DISCHARGE'::text])))
);


--
-- Name: TABLE efficiency_curve; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.efficiency_curve IS 'One-way efficiency lookup vs power fraction and SOC band (RTE is charge*discharge).';


--
-- Name: ems_controller; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.ems_controller (
    ems_id bigint NOT NULL,
    ems_code text NOT NULL,
    battery_system_id bigint,
    source_uuid uuid,
    manufacturer text,
    model text,
    firmware_version text,
    control_mode text
);


--
-- Name: ems_controller_ems_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.ems_controller ALTER COLUMN ems_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.ems_controller_ems_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: ems_dispatch_mode; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.ems_dispatch_mode (
    mode_code text NOT NULL,
    description text
);


--
-- Name: ems_grid_service; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.ems_grid_service (
    service_code text NOT NULL,
    description text
);


--
-- Name: ems_tariff_period; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.ems_tariff_period (
    tariff_period_id bigint NOT NULL,
    ems_id bigint,
    band_code text NOT NULL,
    band_name text NOT NULL,
    price_level text NOT NULL,
    start_hour smallint NOT NULL,
    end_hour smallint NOT NULL,
    day_type text DEFAULT 'ALL'::text NOT NULL,
    season text DEFAULT 'ALL'::text NOT NULL,
    reference_price_mwh numeric,
    valid_from date,
    valid_to date,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ems_tariff_day_type CHECK ((day_type = ANY (ARRAY['ALL'::text, 'WEEKDAY'::text, 'WEEKEND'::text]))),
    CONSTRAINT ems_tariff_hours CHECK ((((start_hour >= 0) AND (start_hour <= 23)) AND ((end_hour >= 1) AND (end_hour <= 24)) AND (end_hour > start_hour))),
    CONSTRAINT ems_tariff_level CHECK ((price_level = ANY (ARRAY['SUPER_OFF_PEAK'::text, 'OFF_PEAK'::text, 'SHOULDER'::text, 'SHOULDER_HIGH'::text, 'PEAK'::text])))
);


--
-- Name: ems_tariff_period_tariff_period_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.ems_tariff_period ALTER COLUMN tariff_period_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.ems_tariff_period_tariff_period_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: eol_criteria; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.eol_criteria (
    chemistry text NOT NULL,
    soh_eol_pct numeric(5,2) NOT NULL,
    resistance_eol_pct numeric(6,2),
    description text
);


--
-- Name: fault_alarm_link; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.fault_alarm_link (
    episode_id text NOT NULL,
    alarm_id text NOT NULL,
    role text,
    CONSTRAINT fault_alarm_link_role_check CHECK ((role = ANY (ARRAY['PRIMARY'::text, 'CONTRIBUTING'::text, 'CONSEQUENTIAL'::text])))
);


--
-- Name: TABLE fault_alarm_link; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.fault_alarm_link IS 'Maps raw alarm events to the confirmed fault episode they belong to (alarm grouping / correlation).';


--
-- Name: fault_catalog; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.fault_catalog (
    fault_code text NOT NULL,
    fault_name text NOT NULL,
    subsystem text NOT NULL,
    category text NOT NULL,
    failure_mode text,
    default_severity smallint,
    is_safety_critical boolean DEFAULT false,
    typical_root_cause text,
    typical_symptoms text,
    recommended_action text,
    standard_ref text
);


--
-- Name: TABLE fault_catalog; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.fault_catalog IS 'Labelled fault classes (the diagnosis/classification target set) — failure modes, not alarm codes.';


--
-- Name: fault_episode; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.fault_episode (
    episode_id text NOT NULL,
    system_id bigint NOT NULL,
    asset_type text,
    asset_code text,
    fault_code text NOT NULL,
    onset_ts timestamp with time zone,
    detected_ts timestamp with time zone NOT NULL,
    resolved_ts timestamp with time zone,
    detection_method text,
    severity_level smallint,
    confirmed_by text,
    label_confidence numeric(4,2),
    root_cause_confirmed text,
    operating_context text,
    downtime_min numeric(9,1),
    energy_lost_kwh numeric(12,2),
    is_ongoing boolean DEFAULT false,
    note text,
    CONSTRAINT chk_episode_window CHECK (((resolved_ts IS NULL) OR (resolved_ts >= detected_ts))),
    CONSTRAINT fault_episode_detection_method_check CHECK ((detection_method = ANY (ARRAY['ALARM'::text, 'MODEL'::text, 'INSPECTION'::text, 'MAINTENANCE'::text, 'OPERATOR'::text])))
);


--
-- Name: TABLE fault_episode; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.fault_episode IS 'Confirmed, labelled fault instances (the supervised training labels); resolved_ts NULL = ongoing/censored.';


--
-- Name: fault_prediction; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.fault_prediction (
    prediction_id bigint NOT NULL,
    model_version text NOT NULL,
    system_id bigint NOT NULL,
    asset_type text,
    asset_code text,
    predicted_at timestamp with time zone NOT NULL,
    predicted_fault_code text NOT NULL,
    probability numeric(5,4),
    top3 text,
    episode_id text,
    actual_fault_code text,
    is_correct boolean,
    note text
);


--
-- Name: TABLE fault_prediction; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.fault_prediction IS 'Classifier predictions vs confirmed labels — the basis for accuracy / precision-recall / confusion matrix.';


--
-- Name: fault_prediction_prediction_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.fault_prediction ALTER COLUMN prediction_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.fault_prediction_prediction_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: fault_signature; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.fault_signature (
    signature_id bigint NOT NULL,
    fault_code text NOT NULL,
    signal text NOT NULL,
    signal_kind text,
    operator text,
    threshold numeric,
    unit text,
    window_min smallint,
    weight numeric(4,2) DEFAULT 1.0,
    note text,
    CONSTRAINT fault_signature_operator_check CHECK ((operator = ANY (ARRAY['>'::text, '<'::text, '>='::text, '<='::text, '=='::text, '!='::text, 'RISING'::text, 'FALLING'::text, 'PRESENT'::text]))),
    CONSTRAINT fault_signature_signal_kind_check CHECK ((signal_kind = ANY (ARRAY['ALARM'::text, 'TELEMETRY'::text, 'FEATURE'::text])))
);


--
-- Name: TABLE fault_signature; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.fault_signature IS 'Symptom->fault diagnostic signatures: the a-priori feature/rule matrix for classification & root-cause ranking.';


--
-- Name: fault_signature_signature_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.fault_signature ALTER COLUMN signature_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.fault_signature_signature_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: generation_asset; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.generation_asset (
    gen_id bigint NOT NULL,
    site_id bigint NOT NULL,
    gen_code text NOT NULL,
    gen_type text NOT NULL,
    rated_kwp numeric(10,2),
    description text,
    CONSTRAINT generation_asset_gen_type_check CHECK ((gen_type = ANY (ARRAY['PV'::text, 'WIND'::text, 'OTHER'::text])))
);


--
-- Name: generation_asset_gen_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.generation_asset ALTER COLUMN gen_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.generation_asset_gen_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: grid_charge; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.grid_charge (
    charge_id bigint NOT NULL,
    site_id bigint NOT NULL,
    charge_type text NOT NULL,
    applies_to text,
    rate numeric(12,4) NOT NULL,
    unit text NOT NULL,
    valid_from date,
    description text,
    CONSTRAINT grid_charge_applies_to_check CHECK ((applies_to = ANY (ARRAY['IMPORT'::text, 'EXPORT'::text, 'BOTH'::text, 'PEAK_DEMAND'::text])))
);


--
-- Name: TABLE grid_charge; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.grid_charge IS 'Cost-stack components on energy moved (wheeling, transmission, demand charge, taxes).';


--
-- Name: grid_charge_charge_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.grid_charge ALTER COLUMN charge_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.grid_charge_charge_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: hvac_cooling_mode; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.hvac_cooling_mode (
    mode_code text NOT NULL,
    description text
);


--
-- Name: hvac_unit; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.hvac_unit (
    hvac_id bigint NOT NULL,
    hvac_code text NOT NULL,
    battery_system_id bigint,
    source_uuid uuid,
    manufacturer text,
    model text,
    hvac_type text,
    cooling_capacity_kw numeric(8,2),
    status text,
    CONSTRAINT hvac_unit_cooling_capacity_kw_check CHECK (((cooling_capacity_kw IS NULL) OR (cooling_capacity_kw >= (0)::numeric)))
);


--
-- Name: hvac_unit_hvac_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.hvac_unit ALTER COLUMN hvac_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.hvac_unit_hvac_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: interconnection_limit; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.interconnection_limit (
    system_id bigint NOT NULL,
    valid_from date NOT NULL,
    poi_export_max_kw numeric(10,2) NOT NULL,
    poi_import_max_kw numeric(10,2) NOT NULL,
    charge_source text,
    note text,
    CONSTRAINT interconnection_limit_charge_source_check CHECK ((charge_source = ANY (ARRAY['GRID'::text, 'PV_ONLY'::text, 'GRID+PV'::text])))
);


--
-- Name: TABLE interconnection_limit; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.interconnection_limit IS 'Point-of-interconnection export/import caps and charging source rule.';


--
-- Name: lifecycle_event; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.lifecycle_event (
    event_id bigint NOT NULL,
    system_id bigint NOT NULL,
    event_type text NOT NULL,
    event_date date NOT NULL,
    age_days integer,
    soh_at_event numeric(5,2),
    failure_mode text,
    note text,
    CONSTRAINT chk_evt CHECK ((event_type = ANY (ARRAY['COMMISSION'::text, 'AUGMENTATION'::text, 'MODULE_REPLACE'::text, 'EOL_REACHED'::text, 'FAILURE'::text, 'DECOMMISSION'::text])))
);


--
-- Name: lifecycle_event_event_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.lifecycle_event ALTER COLUMN event_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.lifecycle_event_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: maintenance_action; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.maintenance_action (
    action_id text NOT NULL,
    episode_id text,
    system_id bigint,
    action_type text,
    component text,
    part_number text,
    part_replaced boolean DEFAULT false,
    labor_hours numeric(6,1),
    cost_usd numeric(10,2),
    performed_by text,
    performed_at timestamp with time zone,
    resolution text,
    fault_confirmed boolean,
    effective boolean,
    note text,
    CONSTRAINT maintenance_action_action_type_check CHECK ((action_type = ANY (ARRAY['INSPECT'::text, 'REPAIR'::text, 'REPLACE'::text, 'RESET'::text, 'CALIBRATE'::text, 'CLEAN'::text, 'FIRMWARE'::text, 'NO_ACTION'::text])))
);


--
-- Name: TABLE maintenance_action; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.maintenance_action IS 'Repair/work-order record per episode: component, parts, cost, MTTR, whether the diagnosis and the fix held.';


--
-- Name: market; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.market (
    market_id bigint NOT NULL,
    market_code text NOT NULL,
    name text NOT NULL,
    currency character(3) DEFAULT 'USD'::bpchar NOT NULL,
    timezone text DEFAULT 'Asia/Kolkata'::text NOT NULL,
    dam_settlement_min smallint DEFAULT 60 NOT NULL,
    rt_settlement_min smallint DEFAULT 15 NOT NULL,
    gate_closure_local text,
    description text
);


--
-- Name: TABLE market; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.market IS 'Market / exchange a node settles in: currency, block lengths, gate closure.';


--
-- Name: market_market_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.market ALTER COLUMN market_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.market_market_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metering_point; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.metering_point (
    metering_point_id bigint NOT NULL,
    site_id bigint NOT NULL,
    mp_code text NOT NULL,
    mp_type text NOT NULL,
    voltage_kv numeric(8,3),
    description text,
    CONSTRAINT chk_mp_type CHECK ((mp_type = ANY (ARRAY['FEEDER'::text, 'POI'::text, 'LOAD'::text, 'SUBSTATION'::text])))
);


--
-- Name: TABLE metering_point; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.metering_point IS 'Revenue/feeder metering points where demand is measured.';


--
-- Name: metering_point_metering_point_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.metering_point ALTER COLUMN metering_point_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.metering_point_metering_point_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: ocv_curve; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.ocv_curve (
    chemistry text NOT NULL,
    direction text NOT NULL,
    temp_c numeric(5,1) NOT NULL,
    soc_pct numeric(5,2) NOT NULL,
    ocv_v numeric(6,4) NOT NULL,
    CONSTRAINT ocv_curve_direction_check CHECK ((direction = ANY (ARRAY['CHARGE'::text, 'DISCHARGE'::text, 'MEAN'::text])))
);


--
-- Name: TABLE ocv_curve; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.ocv_curve IS 'Per-cell OCV vs SOC by direction (hysteresis) and temperature.';


--
-- Name: operating_mode; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.operating_mode (
    mode_code text NOT NULL,
    description text
);


--
-- Name: optimization_run; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.optimization_run (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    issued_at timestamp with time zone NOT NULL,
    horizon_start timestamp with time zone NOT NULL,
    horizon_end timestamp with time zone NOT NULL,
    resolution_min smallint NOT NULL,
    method text,
    objective text,
    solver_status text,
    expected_profit_usd numeric(12,2),
    solve_seconds numeric(8,3),
    study_id bigint,
    CONSTRAINT chk_run_window CHECK ((horizon_end > horizon_start))
);


--
-- Name: TABLE optimization_run; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.optimization_run IS 'One optimizer run: horizon, method, objective, solver status, expected profit.';


--
-- Name: optimization_run_run_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.optimization_run ALTER COLUMN run_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME battery_master.optimization_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: pcs; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.pcs (
    pcs_id bigint NOT NULL,
    pcs_code text NOT NULL,
    manufacturer text,
    model text,
    serial_number text,
    topology text,
    cooling text,
    rated_power_kw numeric(9,2) NOT NULL,
    rated_apparent_kva numeric(9,2),
    max_charge_kw numeric(9,2),
    max_discharge_kw numeric(9,2),
    rated_ac_voltage_v numeric(8,2) NOT NULL,
    ac_frequency_hz numeric(4,1) DEFAULT 50.0 NOT NULL,
    phases smallint DEFAULT 3 NOT NULL,
    dc_voltage_min_v numeric(8,2),
    dc_voltage_max_v numeric(8,2),
    dc_voltage_nom_v numeric(8,2),
    min_power_factor numeric(4,3),
    grid_code text,
    firmware text,
    commissioned_on date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    system_id bigint NOT NULL,
    source_uuid uuid,
    efficiency_pct numeric(5,2),
    grid_mode text,
    CONSTRAINT chk_pcs_dcwin CHECK (((dc_voltage_min_v IS NULL) OR (dc_voltage_max_v IS NULL) OR (dc_voltage_min_v <= dc_voltage_max_v))),
    CONSTRAINT chk_pcs_phases CHECK ((phases = ANY (ARRAY[1, 3]))),
    CONSTRAINT chk_pcs_power CHECK ((rated_power_kw > (0)::numeric)),
    CONSTRAINT pcs_efficiency_pct_check CHECK (((efficiency_pct IS NULL) OR ((efficiency_pct >= (0)::numeric) AND (efficiency_pct <= (100)::numeric))))
);


--
-- Name: TABLE pcs; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.pcs IS 'A power conversion (inverter) unit within a BESS system.';


--
-- Name: pcs_alarm_type; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.pcs_alarm_type (
    alarm_type_code text NOT NULL,
    description text NOT NULL,
    default_severity smallint NOT NULL,
    category text NOT NULL,
    CONSTRAINT chk_pcs_alarm_cat CHECK ((category = ANY (ARRAY['AC'::text, 'DC'::text, 'THERMAL'::text, 'GRID'::text, 'INTERNAL'::text])))
);


--
-- Name: TABLE pcs_alarm_type; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.pcs_alarm_type IS 'Catalog of PCS alarm/fault codes.';


--
-- Name: pcs_breaker_state; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.pcs_breaker_state (
    state_code text NOT NULL,
    description text NOT NULL
);


--
-- Name: pcs_command_type; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.pcs_command_type (
    command_code text NOT NULL,
    description text NOT NULL
);


--
-- Name: pcs_grid_service; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.pcs_grid_service (
    service_code text NOT NULL,
    description text NOT NULL
);


--
-- Name: TABLE pcs_grid_service; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.pcs_grid_service IS 'Grid-support functions the PCS can perform.';


--
-- Name: pcs_mode; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.pcs_mode (
    mode_code text NOT NULL,
    description text NOT NULL
);


--
-- Name: TABLE pcs_mode; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.pcs_mode IS 'PCS operating states (control modes).';


--
-- Name: pcs_pcs_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.pcs ALTER COLUMN pcs_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.pcs_pcs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: pcs_ride_through_type; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.pcs_ride_through_type (
    rt_code text NOT NULL,
    description text NOT NULL
);


--
-- Name: price_node; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.price_node (
    node_id bigint NOT NULL,
    market_id bigint NOT NULL,
    node_code text NOT NULL,
    name text,
    node_type text,
    site_id bigint,
    CONSTRAINT price_node_node_type_check CHECK ((node_type = ANY (ARRAY['ZONE'::text, 'HUB'::text, 'NODE'::text, 'POI'::text])))
);


--
-- Name: TABLE price_node; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.price_node IS 'Settlement node / bidding zone the plant is priced at.';


--
-- Name: price_node_node_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.price_node ALTER COLUMN node_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.price_node_node_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: site; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.site (
    site_code character varying(50) NOT NULL,
    site_name character varying(200) NOT NULL,
    latitude numeric(10,7),
    longitude numeric(10,7),
    address text,
    rated_power_mw numeric(10,2),
    rated_energy_mwh numeric(10,2),
    commission_date date,
    created_at timestamp with time zone DEFAULT now(),
    timezone text DEFAULT 'UTC'::text NOT NULL,
    grid_operator text,
    state text,
    site_id bigint NOT NULL,
    source_uuid uuid,
    grid_voltage_kv numeric(8,2)
);


--
-- Name: site_site_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.site ALTER COLUMN site_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME battery_master.site_site_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: soc_reference; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.soc_reference (
    system_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    soc_true_pct numeric(5,2) NOT NULL,
    method text,
    note text,
    CONSTRAINT soc_reference_method_check CHECK ((method = ANY (ARRAY['FULL_CHARGE'::text, 'FULL_DISCHARGE'::text, 'LAB_RPT'::text, 'REST_OCV'::text])))
);


--
-- Name: TABLE soc_reference; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON TABLE battery_master.soc_reference IS 'Independent ground-truth SOC (recalibration / lab anchors) — the label.';


--
-- Name: tenant; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.tenant (
    tenant_id bigint NOT NULL,
    name character varying(200) NOT NULL,
    legal_name character varying(200),
    tenant_type battery_master.tenant_type,
    address_line1 character varying(200),
    address_line2 character varying(200),
    city character varying(100),
    state_province character varying(100),
    postal_code character varying(20),
    country character varying(100),
    phone character varying(30),
    email character varying(200),
    status battery_master.tenant_status DEFAULT 'active'::battery_master.tenant_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    source_uuid uuid
);


--
-- Name: tenant_contact; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.tenant_contact (
    contact_id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    contact_name character varying(200) NOT NULL,
    role character varying(50),
    phone character varying(30),
    email character varying(200),
    is_primary boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tenant_contact_contact_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.tenant_contact ALTER COLUMN contact_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME battery_master.tenant_contact_contact_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: tenant_site; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.tenant_site (
    tenant_id bigint NOT NULL,
    site_id bigint NOT NULL,
    ownership_pct numeric(5,2),
    is_primary_owner boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tenant_tenant_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.tenant ALTER COLUMN tenant_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME battery_master.tenant_tenant_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: transformer; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.transformer (
    transformer_name character varying(100),
    hv_voltage_kv numeric(10,2),
    lv_voltage_kv numeric(10,2),
    rating_mva numeric(10,2),
    transformer_id bigint NOT NULL,
    site_id bigint NOT NULL
);


--
-- Name: transformer_transformer_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.transformer ALTER COLUMN transformer_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME battery_master.transformer_transformer_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: v_arbitrage_features; Type: VIEW; Schema: battery_master; Owner: -
--

CREATE VIEW battery_master.v_arbitrage_features AS
 WITH latest_fc AS (
         SELECT DISTINCT ON (price_forecast.node_id, price_forecast.target_ts) price_forecast.node_id,
            price_forecast.target_ts,
            price_forecast.issued_at,
            price_forecast.horizon_h,
            price_forecast.p10_mwh,
            price_forecast.p50_mwh,
            price_forecast.p90_mwh
           FROM battery_master.price_forecast
          ORDER BY price_forecast.node_id, price_forecast.target_ts, price_forecast.issued_at DESC
        )
 SELECT rt.node_id,
    rt.interval_start,
    rt.price_mwh AS rt_price_mwh,
    da.price_mwh AS dam_price_mwh,
    fc.p10_mwh,
    fc.p50_mwh,
    fc.p90_mwh,
    (fc.p90_mwh - fc.p10_mwh) AS forecast_band_mwh,
    bp.usable_energy_mwh,
    bp.soc_min_pct,
    bp.soc_max_pct,
    bp.p_charge_max_kw,
    bp.p_discharge_max_kw,
    bp.ramp_kw_per_min,
    bp.rte_ac,
    bp.max_cycles_per_day,
    bp.degradation_cost_mwh,
    il.poi_export_max_kw,
    il.poi_import_max_kw
   FROM ((((((battery_master.rt_price rt
     LEFT JOIN battery_master.dam_price da ON (((da.node_id = rt.node_id) AND (da.delivery_start = date_trunc('hour'::text, rt.interval_start)))))
     LEFT JOIN latest_fc fc ON (((fc.node_id = rt.node_id) AND (fc.target_ts = date_trunc('hour'::text, rt.interval_start)))))
     LEFT JOIN battery_master.price_node pn ON ((pn.node_id = rt.node_id)))
     LEFT JOIN battery_master.battery_system bs ON ((bs.site_id = pn.site_id)))
     LEFT JOIN LATERAL ( SELECT p.param_id,
            p.system_id,
            p.valid_from,
            p.usable_energy_mwh,
            p.soc_min_pct,
            p.soc_max_pct,
            p.p_charge_max_kw,
            p.p_discharge_max_kw,
            p.ramp_kw_per_min,
            p.rte_ac,
            p.self_discharge_pct_day,
            p.max_cycles_per_day,
            p.min_dwell_min,
            p.degradation_cost_mwh,
            p.aux_load_kw
           FROM battery_master.battery_opt_param p
          WHERE ((p.system_id = bs.battery_system_id) AND (p.valid_from <= (rt.interval_start)::date))
          ORDER BY p.valid_from DESC
         LIMIT 1) bp ON (true))
     LEFT JOIN LATERAL ( SELECT i.system_id,
            i.valid_from,
            i.poi_export_max_kw,
            i.poi_import_max_kw,
            i.charge_source,
            i.note
           FROM battery_master.interconnection_limit i
          WHERE ((i.system_id = bs.battery_system_id) AND (i.valid_from <= (rt.interval_start)::date))
          ORDER BY i.valid_from DESC
         LIMIT 1) il ON (true));


--
-- Name: VIEW v_arbitrage_features; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON VIEW battery_master.v_arbitrage_features IS 'MILP/RL input per interval: realized + day-ahead + forecast prices with the cost/constraint parameters.';


--
-- Name: v_dispatch_pnl; Type: VIEW; Schema: battery_master; Owner: -
--

CREATE VIEW battery_master.v_dispatch_pnl AS
 SELECT system_id,
    ((interval_start AT TIME ZONE 'Asia/Kolkata'::text))::date AS local_day,
    sum(
        CASE
            WHEN (energy_mwh > (0)::numeric) THEN energy_mwh
            ELSE (0)::numeric
        END) AS discharge_mwh,
    sum(
        CASE
            WHEN (energy_mwh < (0)::numeric) THEN (- energy_mwh)
            ELSE (0)::numeric
        END) AS charge_mwh,
    sum(gross_revenue_usd) AS gross_revenue_usd,
    sum(degradation_cost_usd) AS degradation_cost_usd,
    sum(grid_cost_usd) AS grid_cost_usd,
    sum(net_pnl_usd) AS net_pnl_usd,
    avg(price_mwh) AS avg_price_mwh
   FROM battery_master.dispatch_outcome o
  GROUP BY system_id, (((interval_start AT TIME ZONE 'Asia/Kolkata'::text))::date);


--
-- Name: VIEW v_dispatch_pnl; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON VIEW battery_master.v_dispatch_pnl IS 'Daily realized P&L: throughput, gross revenue, degradation and grid cost, net profit.';


--
-- Name: v_fault_scoring; Type: VIEW; Schema: battery_master; Owner: -
--

CREATE VIEW battery_master.v_fault_scoring AS
 SELECT model_version,
    actual_fault_code,
    predicted_fault_code,
    count(*) AS n,
    avg(probability) AS avg_confidence,
    sum(
        CASE
            WHEN is_correct THEN 1
            ELSE 0
        END) AS n_correct
   FROM battery_master.fault_prediction p
  WHERE (actual_fault_code IS NOT NULL)
  GROUP BY model_version, actual_fault_code, predicted_fault_code;


--
-- Name: VIEW v_fault_scoring; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON VIEW battery_master.v_fault_scoring IS 'Confusion-matrix rows (actual x predicted) with counts and confidence for classifier evaluation.';


--
-- Name: v_fault_signature_profile; Type: VIEW; Schema: battery_master; Owner: -
--

CREATE VIEW battery_master.v_fault_signature_profile AS
 SELECT fc.fault_code,
    fc.fault_name,
    fc.subsystem,
    count(fs.signature_id) AS n_signatures,
    sum(fs.weight) AS total_weight,
    string_agg(((fs.signal || COALESCE(fs.operator, ''::text)) || COALESCE((fs.threshold)::text, ''::text)), ' ; '::text ORDER BY fs.weight DESC) AS signature_summary
   FROM (battery_master.fault_catalog fc
     LEFT JOIN battery_master.fault_signature fs ON ((fs.fault_code = fc.fault_code)))
  GROUP BY fc.fault_code, fc.fault_name, fc.subsystem;


--
-- Name: VIEW v_fault_signature_profile; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON VIEW battery_master.v_fault_signature_profile IS 'Per-fault diagnostic signature profile (symptom set + weights) for the diagnosis engine.';


--
-- Name: v_fault_training; Type: VIEW; Schema: battery_master; Owner: -
--

CREATE VIEW battery_master.v_fault_training AS
SELECT
    NULL::text AS episode_id,
    NULL::bigint AS system_id,
    NULL::character varying(100) AS system_name,
    NULL::text AS asset_type,
    NULL::text AS asset_code,
    NULL::text AS fault_code,
    NULL::text AS subsystem,
    NULL::text AS category,
    NULL::text AS failure_mode,
    NULL::boolean AS is_safety_critical,
    NULL::timestamp with time zone AS onset_ts,
    NULL::timestamp with time zone AS detected_ts,
    NULL::timestamp with time zone AS resolved_ts,
    NULL::numeric AS lead_time_min,
    NULL::numeric AS duration_h,
    NULL::text AS detection_method,
    NULL::smallint AS severity_level,
    NULL::numeric(4,2) AS label_confidence,
    NULL::text AS root_cause_confirmed,
    NULL::text AS operating_context,
    NULL::numeric(9,1) AS downtime_min,
    NULL::numeric(12,2) AS energy_lost_kwh,
    NULL::boolean AS is_ongoing,
    NULL::bigint AS n_alarms,
    NULL::text AS alarm_ids,
    NULL::boolean AS part_replaced,
    NULL::numeric AS repair_cost_usd,
    NULL::boolean AS repair_effective;


--
-- Name: VIEW v_fault_training; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON VIEW battery_master.v_fault_training IS 'Supervised fault-classification training set: features + fault_code label + outcome, one row per confirmed episode.';


--
-- Name: v_rul_training; Type: VIEW; Schema: battery_master; Owner: -
--

CREATE VIEW battery_master.v_rul_training AS
 SELECT a.system_id,
    s.system_name AS system_code,
    a.snapshot_date,
    a.age_days,
    a.calendar_age_years,
    a.cum_throughput_mwh,
    a.equiv_full_cycles,
    a.avg_dod_pct,
    a.avg_cell_temp_c,
    a.days_at_high_soc,
    a.soh_pct,
    a.internal_resistance_mohm,
    p.batch_lot,
    p.usage_cycles_per_day,
    p.climate_avg_temp_c,
    p.bol_capacity_kwh,
    a.rul_days,
    a.rul_cycles,
    a.is_censored,
    a.eol_reached
   FROM ((battery_master.aging_snapshot a
     JOIN battery_master.battery_system s ON ((s.battery_system_id = a.system_id)))
     LEFT JOIN battery_master.battery_provenance p ON ((p.system_id = a.system_id)));


--
-- Name: v_soc_features; Type: VIEW; Schema: battery_master; Owner: -
--

CREATE VIEW battery_master.v_soc_features AS
 SELECT t.system_id,
    t.ts,
    t.soc_coulomb_pct,
    t.soc_bms_pct,
    t.measured_current_a,
    t.current_sensor_offset_a,
    t.pack_voltage_v,
    t.cell_v_avg_v,
    t.ocv_rested_v,
    t.cell_temp_avg_c,
    t.usable_capacity_ah,
    t.c_rate,
    t.coulombic_efficiency,
    t.at_rest,
    t.rest_duration_min,
    r.soc_true_pct,
    (r.soc_true_pct - t.soc_coulomb_pct) AS soc_error_vs_coulomb,
    (r.soc_true_pct - t.soc_bms_pct) AS soc_error_vs_bms,
    r.method AS reference_method
   FROM (battery_telemetry.system_telemetry t
     LEFT JOIN battery_master.soc_reference r ON (((r.system_id = t.system_id) AND (r.ts = t.ts))));


--
-- Name: VIEW v_soc_features; Type: COMMENT; Schema: battery_master; Owner: -
--

COMMENT ON VIEW battery_master.v_soc_features IS 'SOC-correction features + ground-truth error labels (target = soc_error_vs_coulomb or soc_true_pct).';


--
-- Name: v_thermal_assets; Type: VIEW; Schema: battery_master; Owner: -
--

CREATE VIEW battery_master.v_thermal_assets AS
 SELECT battery_system_id,
    ( SELECT min(p.pcs_id) AS min
           FROM battery_master.pcs p
          WHERE (p.system_id = bs.battery_system_id)) AS pcs_id,
    ( SELECT min(h.hvac_id) AS min
           FROM battery_master.hvac_unit h
          WHERE (h.battery_system_id = bs.battery_system_id)) AS hvac_id,
    ( SELECT min(e.ems_id) AS min
           FROM battery_master.ems_controller e
          WHERE (e.battery_system_id = bs.battery_system_id)) AS ems_id
   FROM battery_master.battery_system bs;


--
-- Name: weather_station; Type: TABLE; Schema: battery_master; Owner: -
--

CREATE TABLE battery_master.weather_station (
    station_id bigint NOT NULL,
    site_id bigint,
    station_code text NOT NULL,
    provider text,
    latitude numeric(9,6),
    longitude numeric(9,6)
);


--
-- Name: weather_station_station_id_seq; Type: SEQUENCE; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.weather_station ALTER COLUMN station_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_master.weather_station_station_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: anomaly_module_result; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.anomaly_module_result (
    run_id bigint NOT NULL,
    module_id bigint NOT NULL,
    serial_number text,
    pack_id bigint,
    pack_number text,
    "position" integer,
    verdict text NOT NULL,
    combined_score numeric NOT NULL,
    rank integer NOT NULL,
    n_points integer NOT NULL,
    if_score_mean numeric,
    if_anomaly_share numeric,
    db_noise_share numeric,
    if_flag boolean NOT NULL,
    db_flag boolean NOT NULL,
    feature_means jsonb DEFAULT '{}'::jsonb NOT NULL,
    reasons jsonb DEFAULT '[]'::jsonb NOT NULL,
    first_anomaly timestamp with time zone,
    CONSTRAINT anomaly_verdict CHECK ((verdict = ANY (ARRAY['WEAK'::text, 'SUSPECT'::text, 'NORMAL'::text])))
);


--
-- Name: anomaly_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.anomaly_point (
    run_id bigint NOT NULL,
    module_id bigint NOT NULL,
    bucket timestamp with time zone NOT NULL,
    features jsonb NOT NULL,
    if_score numeric,
    if_flag boolean,
    db_label integer
);


--
-- Name: anomaly_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.anomaly_run (
    run_id bigint NOT NULL,
    use_case text DEFAULT 'weak_module'::text NOT NULL,
    run_kind text DEFAULT 'train'::text NOT NULL,
    parent_run_id bigint,
    run_name text,
    status text NOT NULL,
    battery_system_id bigint NOT NULL,
    system_name text NOT NULL,
    date_from date,
    date_to date,
    grain text NOT NULL,
    feature_groups text[] NOT NULL,
    features text[] NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    n_rows integer,
    n_modules integer,
    n_packs integer,
    if_anomalies integer,
    db_noise integer,
    db_clusters integer,
    eps_used numeric,
    silhouette numeric,
    n_weak integer,
    n_suspect integer,
    feature_stats jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT anomaly_run_grain CHECK ((grain = ANY (ARRAY['hour'::text, 'day'::text]))),
    CONSTRAINT anomaly_run_kind CHECK ((run_kind = ANY (ARRAY['train'::text, 'score'::text]))),
    CONSTRAINT anomaly_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: anomaly_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.anomaly_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.anomaly_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: arb_backtest; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.arb_backtest (
    study_id bigint NOT NULL,
    kind text NOT NULL,
    interval_start timestamp with time zone NOT NULL,
    run_id bigint,
    p_kw numeric(10,2),
    c_as_mw numeric(8,3),
    soc_pct numeric(6,2),
    rt_price_mwh numeric(10,2),
    fc_price_mwh numeric(10,2),
    energy_mwh numeric(12,6),
    gross_usd numeric(12,4),
    degradation_usd numeric(12,4),
    grid_usd numeric(12,4),
    as_usd numeric(12,4),
    net_usd numeric(12,4),
    CONSTRAINT arb_backtest_kind_check CHECK ((kind = ANY (ARRAY['policy'::text, 'oracle'::text])))
);


--
-- Name: arb_study; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.arb_study (
    study_id bigint NOT NULL,
    study_name text,
    status text NOT NULL,
    system_id bigint NOT NULL,
    node_id bigint NOT NULL,
    date_from date NOT NULL,
    date_to date NOT NULL,
    mode text NOT NULL,
    params jsonb NOT NULL,
    metrics jsonb,
    checks jsonb,
    warnings jsonb,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT arb_study_status_check CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: arb_study_day; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.arb_study_day (
    study_id bigint NOT NULL,
    kpi_date date NOT NULL,
    run_id bigint,
    solver_status text,
    solve_seconds numeric(10,3),
    expected_profit_usd numeric(12,2),
    gross_usd numeric(12,4),
    degradation_usd numeric(12,4),
    grid_usd numeric(12,4),
    net_usd numeric(12,4),
    oracle_net_usd numeric(12,4),
    pack_net_usd numeric(12,4),
    discharge_mwh numeric(12,6),
    charge_mwh numeric(12,6),
    cycles numeric(8,4),
    soc_start_pct numeric(6,2),
    soc_end_pct numeric(6,2),
    checks jsonb
);


--
-- Name: arb_study_study_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.arb_study ALTER COLUMN study_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.arb_study_study_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aux_forecast_daily; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.aux_forecast_daily (
    run_id bigint NOT NULL,
    ems_id bigint NOT NULL,
    day date NOT NULL,
    method text NOT NULL,
    actual_kwh numeric,
    p10_kwh numeric,
    p50_kwh numeric,
    p90_kwh numeric
);


--
-- Name: aux_forecast_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.aux_forecast_point (
    run_id bigint NOT NULL,
    ems_id bigint NOT NULL,
    origin_ts timestamp with time zone NOT NULL,
    horizon_min smallint NOT NULL,
    method text NOT NULL,
    p10 real,
    p50 real,
    p90 real,
    actual real
);


--
-- Name: aux_forecast_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.aux_forecast_run (
    run_id bigint NOT NULL,
    use_case text DEFAULT 'aux_forecast'::text NOT NULL,
    run_name text,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    ems_ids bigint[] NOT NULL,
    date_from date,
    date_to date,
    horizon_hours integer NOT NULL,
    test_fraction numeric NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    n_train_rows integer,
    n_test_rows integer,
    metrics jsonb,
    results jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT aux_forecast_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: aux_forecast_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.aux_forecast_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.aux_forecast_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aux_forecast_score; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.aux_forecast_score (
    run_id bigint NOT NULL,
    ems_id bigint NOT NULL,
    horizon_bucket text NOT NULL,
    method text NOT NULL,
    n integer,
    mae numeric,
    rmse numeric,
    pinball numeric,
    coverage_pct numeric,
    bias numeric
);


--
-- Name: bms_kpi; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.bms_kpi (
    system_id bigint NOT NULL,
    kpi_date date NOT NULL,
    kpi_code text NOT NULL,
    kpi_name text NOT NULL,
    unit text,
    value numeric,
    sample_count integer NOT NULL,
    config_version integer NOT NULL,
    config_hash text NOT NULL,
    run_id bigint,
    calculated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE bms_kpi; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.bms_kpi IS 'Daily BMS KPIs per battery system, computed from system_telemetry by the definitions in kpi_config/bms_kpi.yaml.';


--
-- Name: bms_kpi_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.bms_kpi_run (
    run_id bigint NOT NULL,
    status text NOT NULL,
    triggered_by text NOT NULL,
    system_ids bigint[],
    start_date date,
    end_date date,
    config_file text NOT NULL,
    config_version integer NOT NULL,
    config_hash text NOT NULL,
    kpi_codes text[] NOT NULL,
    systems_done integer,
    days integer,
    rows_deleted integer,
    rows_written integer,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT bms_kpi_run_status_check CHECK ((status = ANY (ARRAY['running'::text, 'success'::text, 'failed'::text])))
);


--
-- Name: TABLE bms_kpi_run; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.bms_kpi_run IS 'One row per BMS KPI calculation (API button or CLI).';


--
-- Name: bms_kpi_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.bms_kpi_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.bms_kpi_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: efficiency_cycle; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.efficiency_cycle (
    run_id bigint NOT NULL,
    cycle_no integer NOT NULL,
    pcs_id bigint NOT NULL,
    battery_system_id bigint,
    start_ts timestamp with time zone NOT NULL,
    end_ts timestamp with time zone NOT NULL,
    data_set text,
    closed boolean NOT NULL,
    complete boolean NOT NULL,
    e_dc_in_kwh numeric,
    e_dc_out_kwh numeric,
    e_ac_in_kwh numeric,
    e_ac_out_kwh numeric,
    e_poi_in_kwh numeric,
    e_poi_out_kwh numeric,
    e_aux_kwh numeric,
    e_hvac_kwh numeric,
    soc_start_pct numeric,
    soc_end_pct numeric,
    depth_pct numeric,
    rte_dc_pct numeric,
    rte_ac_pct numeric,
    rte_sys_pct numeric,
    rte_dc_pred_pct numeric,
    rte_ac_comp_pct numeric,
    rte_sys_comp_pct numeric,
    eta_chg_meas_pct numeric,
    eta_dis_meas_pct numeric,
    eta_chg_pred_pct numeric,
    eta_dis_pred_pct numeric,
    detail jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: efficiency_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.efficiency_run (
    run_id bigint NOT NULL,
    use_case text DEFAULT 'efficiency'::text NOT NULL,
    run_name text,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    pcs_ids bigint[] NOT NULL,
    date_from date,
    date_to date,
    split_method text NOT NULL,
    test_fraction numeric NOT NULL,
    min_load_frac numeric NOT NULL,
    feature_groups text[] NOT NULL,
    features text[],
    booster text NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    n_points integer,
    n_train integer,
    n_test integer,
    n_cycles integer,
    best_model text,
    metrics jsonb,
    results jsonb,
    predictions jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT efficiency_run_booster CHECK ((booster = ANY (ARRAY['lightgbm'::text, 'xgboost'::text]))),
    CONSTRAINT efficiency_run_split CHECK ((split_method = ANY (ARRAY['chronological'::text, 'random'::text]))),
    CONSTRAINT efficiency_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: efficiency_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.efficiency_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.efficiency_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: efficiency_score; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.efficiency_score (
    run_id bigint NOT NULL,
    model text NOT NULL,
    dataset text NOT NULL,
    n integer,
    r2 numeric,
    mae numeric,
    rmse numeric,
    mape_pct numeric,
    max_error numeric,
    median_ae numeric,
    loss_mae_kw numeric,
    bias_pp numeric,
    CONSTRAINT efficiency_score_dataset CHECK ((dataset = ANY (ARRAY['train'::text, 'test'::text, 'cv'::text, 'all'::text])))
);


--
-- Name: ems_kpi; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.ems_kpi (
    ems_id bigint NOT NULL,
    kpi_date date NOT NULL,
    kpi_code text NOT NULL,
    kpi_name text NOT NULL,
    unit text,
    value numeric,
    sample_count integer NOT NULL,
    config_version integer NOT NULL,
    config_hash text NOT NULL,
    run_id bigint,
    calculated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE ems_kpi; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.ems_kpi IS 'Daily EMS KPIs per EMS controller, computed from ems_telemetry by the definitions in kpi_config/ems_kpi.yaml.';


--
-- Name: ems_kpi_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.ems_kpi_run (
    run_id bigint NOT NULL,
    status text NOT NULL,
    triggered_by text NOT NULL,
    ems_ids bigint[],
    start_date date,
    end_date date,
    config_file text NOT NULL,
    config_version integer NOT NULL,
    config_hash text NOT NULL,
    kpi_codes text[] NOT NULL,
    systems_done integer,
    days integer,
    rows_deleted integer,
    rows_written integer,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT ems_kpi_run_status_check CHECK ((status = ANY (ARRAY['running'::text, 'success'::text, 'failed'::text])))
);


--
-- Name: TABLE ems_kpi_run; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.ems_kpi_run IS 'One row per EMS KPI calculation (API button or CLI).';


--
-- Name: ems_kpi_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.ems_kpi_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.ems_kpi_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: fault_diag_candidate; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.fault_diag_candidate (
    candidate_id bigint NOT NULL,
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    first_ts timestamp with time zone NOT NULL,
    peak_ts timestamp with time zone NOT NULL,
    last_ts timestamp with time zone NOT NULL,
    fault_code text NOT NULL,
    probability numeric(6,4),
    n_windows integer DEFAULT 1 NOT NULL,
    top3 jsonb,
    contributions jsonb,
    evidence jsonb,
    alarms text[],
    asset_code text,
    episode_id text,
    actual_fault_code text,
    prediction_id bigint,
    status text DEFAULT 'NEW'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT fault_diag_candidate_status_check CHECK ((status = ANY (ARRAY['NEW'::text, 'CONFIRMED'::text, 'REJECTED'::text])))
);


--
-- Name: fault_diag_candidate_candidate_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.fault_diag_candidate ALTER COLUMN candidate_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.fault_diag_candidate_candidate_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: fault_diag_example; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.fault_diag_example (
    run_id bigint NOT NULL,
    example_key text NOT NULL,
    group_key text NOT NULL,
    kind text NOT NULL,
    episode_id text,
    system_id bigint,
    window_start timestamp with time zone NOT NULL,
    window_end timestamp with time zone NOT NULL,
    label text NOT NULL,
    predicted text NOT NULL,
    probability numeric(6,4),
    correct boolean NOT NULL,
    fold smallint,
    detail jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: fault_diag_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.fault_diag_run (
    run_id bigint NOT NULL,
    run_name text,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    date_from date,
    date_to date,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    summary jsonb,
    metrics jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    artifact_path text,
    published_at timestamp with time zone,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT fault_diag_run_status_check CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: fault_diag_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.fault_diag_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.fault_diag_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: fault_diag_scan_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.fault_diag_scan_point (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    predicted text NOT NULL,
    probability numeric(6,4),
    p_none numeric(6,4),
    top3 jsonb,
    alarms text[]
);


--
-- Name: heatload_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.heatload_run (
    run_id bigint NOT NULL,
    run_name text,
    status text NOT NULL,
    system_ids bigint[] NOT NULL,
    date_from date NOT NULL,
    date_to date NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    models jsonb,
    summary jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT heatload_run_status_check CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: heatload_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.heatload_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.heatload_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: hvac_cop_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.hvac_cop_run (
    run_id bigint NOT NULL,
    run_name text,
    status text NOT NULL,
    hvac_ids bigint[] NOT NULL,
    date_from date NOT NULL,
    date_to date NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    models jsonb,
    summary jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT hvac_cop_run_status_check CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: hvac_cop_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.hvac_cop_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.hvac_cop_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: loss_daily; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.loss_daily (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    day date NOT NULL,
    intervals integer NOT NULL,
    is_baseline boolean DEFAULT false NOT NULL,
    e_in_poi_kwh numeric(14,3),
    e_out_poi_kwh numeric(14,3),
    e_in_ac_kwh numeric(14,3),
    e_out_ac_kwh numeric(14,3),
    e_in_term_kwh numeric(14,3),
    e_out_term_kwh numeric(14,3),
    stored_kwh numeric(14,3),
    throughput_kwh numeric(14,3),
    utilization_pct numeric(8,3),
    loss_batt_kwh numeric(12,3),
    loss_dc_kwh numeric(12,3),
    loss_pcs_kwh numeric(12,3),
    loss_xfmr_kwh numeric(12,3),
    aux_hvac_kwh numeric(12,3),
    aux_ctrl_kwh numeric(12,3),
    standby_kwh numeric(12,3),
    exp_batt_kwh numeric(12,3),
    exp_pcs_kwh numeric(12,3),
    exp_xfmr_kwh numeric(12,3),
    exp_aux_kwh numeric(12,3),
    exp_standby_kwh numeric(12,3),
    fixed_kwh numeric(12,3),
    variable_kwh numeric(12,3),
    rte_term numeric(8,5),
    rte_dc numeric(8,5),
    rte_ac numeric(8,5),
    rte_poi_excl_aux numeric(8,5),
    rte_plant numeric(8,5),
    rte_expected numeric(8,5),
    performance_ratio numeric(8,5),
    guarantee_gap_pts numeric(8,4),
    closure_kwh numeric(12,4),
    closure_pcs_kwh numeric(12,4),
    avg_price_mwh numeric(10,3),
    loss_usd numeric(12,4),
    excess_usd numeric(12,4),
    extra jsonb
);


--
-- Name: loss_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.loss_run (
    run_id bigint NOT NULL,
    run_name text,
    status text NOT NULL,
    system_ids bigint[] NOT NULL,
    date_from date NOT NULL,
    date_to date NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    models jsonb,
    summary jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT loss_run_status_check CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: loss_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.loss_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.loss_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: model_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.model_run (
    run_id bigint NOT NULL,
    run_name text,
    model_type text NOT NULL,
    status text DEFAULT 'RUNNING'::text NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    target text DEFAULT 'soh_pct'::text NOT NULL,
    grain text NOT NULL,
    date_from date,
    date_to date,
    feature_groups text[] DEFAULT '{}'::text[] NOT NULL,
    features text[] DEFAULT '{}'::text[] NOT NULL,
    module_rows_only boolean DEFAULT false NOT NULL,
    include_snapshots boolean DEFAULT false NOT NULL,
    split_method text NOT NULL,
    test_fraction numeric NOT NULL,
    random_state integer DEFAULT 42 NOT NULL,
    n_rows integer,
    n_train integer,
    n_test integer,
    train_from timestamp with time zone,
    train_to timestamp with time zone,
    test_from timestamp with time zone,
    test_to timestamp with time zone,
    target_min numeric,
    target_max numeric,
    target_std numeric,
    r2 numeric,
    mae numeric,
    rmse numeric,
    mape_pct numeric,
    max_error numeric,
    median_ae numeric,
    explained_variance numeric,
    train_r2 numeric,
    train_mae numeric,
    train_rmse numeric,
    iterations integer,
    best_iteration integer,
    feature_importance jsonb,
    feature_ranges jsonb,
    predictions jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    is_active boolean DEFAULT false NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    min_importance_pct numeric DEFAULT 0 NOT NULL,
    importance_method text,
    candidate_features text[],
    selection_importance jsonb,
    use_case text DEFAULT 'soh'::text NOT NULL,
    scope text DEFAULT 'base'::text NOT NULL,
    site_id bigint,
    battery_system_id bigint,
    training_mode text DEFAULT 'scratch'::text NOT NULL,
    parent_run_id bigint,
    systems bigint[],
    holdout_system_id bigint,
    metrics_by_system jsonb,
    holdout_metrics jsonb,
    CONSTRAINT model_run_finetune_parent CHECK (((training_mode = 'scratch'::text) OR (scope = 'system'::text))),
    CONSTRAINT model_run_fraction CHECK (((test_fraction > (0)::numeric) AND (test_fraction < (1)::numeric))),
    CONSTRAINT model_run_grain CHECK ((grain = ANY (ARRAY['5min'::text, 'hour'::text, 'day'::text]))),
    CONSTRAINT model_run_importance_method CHECK (((importance_method IS NULL) OR (importance_method = ANY (ARRAY['gain'::text, 'permutation'::text])))),
    CONSTRAINT model_run_scope CHECK ((scope = ANY (ARRAY['base'::text, 'system'::text]))),
    CONSTRAINT model_run_scope_system CHECK ((((scope = 'base'::text) AND (battery_system_id IS NULL)) OR ((scope = 'system'::text) AND (battery_system_id IS NOT NULL)))),
    CONSTRAINT model_run_split CHECK ((split_method = ANY (ARRAY['chronological'::text, 'random'::text]))),
    CONSTRAINT model_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text]))),
    CONSTRAINT model_run_threshold CHECK (((min_importance_pct >= (0)::numeric) AND (min_importance_pct < (100)::numeric))),
    CONSTRAINT model_run_training_mode CHECK ((training_mode = ANY (ARRAY['scratch'::text, 'finetune'::text]))),
    CONSTRAINT model_run_type CHECK ((model_type = ANY (ARRAY['xgboost'::text, 'lightgbm'::text])))
);


--
-- Name: TABLE model_run; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.model_run IS 'SOH model training runs (XGBoost / LightGBM) with their scores';


--
-- Name: model_run_curve; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.model_run_curve (
    run_id bigint NOT NULL,
    iteration integer NOT NULL,
    train_rmse numeric,
    valid_rmse numeric,
    train_mae numeric,
    valid_mae numeric
);


--
-- Name: TABLE model_run_curve; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.model_run_curve IS 'Train/validation error per boosting round of a model run';


--
-- Name: model_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.model_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.model_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: mv_anomaly_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.mv_anomaly_run (
    run_id bigint NOT NULL,
    run_name text,
    run_kind text DEFAULT 'train'::text NOT NULL,
    parent_run_id bigint,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    system_id bigint NOT NULL,
    date_from date,
    date_to date,
    eval_from timestamp with time zone,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    features jsonb,
    thresholds jsonb,
    metrics jsonb,
    summary jsonb,
    warnings jsonb,
    artifact_path text,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT mv_anomaly_run_run_kind_check CHECK ((run_kind = ANY (ARRAY['train'::text, 'score'::text, 'live'::text]))),
    CONSTRAINT mv_anomaly_run_status_check CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: TABLE mv_anomaly_run; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.mv_anomaly_run IS 'Multivariate anomaly detection runs: model builds (train), scorings of other windows (score), live micro-batch target (live).';


--
-- Name: mv_anomaly_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.mv_anomaly_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.mv_anomaly_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: netload_forecast_peak; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.netload_forecast_peak (
    run_id bigint NOT NULL,
    mp_id bigint NOT NULL,
    origin_ts timestamp with time zone NOT NULL,
    target_date date NOT NULL,
    model text NOT NULL,
    lead_h real,
    p10 real,
    p50 real,
    p90 real,
    peak_ts timestamp with time zone,
    prob_exceed real,
    actual real,
    actual_ts timestamp with time zone,
    threshold_kw real
);


--
-- Name: netload_forecast_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.netload_forecast_point (
    run_id bigint NOT NULL,
    mp_id bigint NOT NULL,
    origin_ts timestamp with time zone NOT NULL,
    target_ts timestamp with time zone NOT NULL,
    step smallint NOT NULL,
    model text NOT NULL,
    p10 real,
    p50 real,
    p90 real,
    actual real
);


--
-- Name: netload_forecast_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.netload_forecast_run (
    run_id bigint NOT NULL,
    use_case text DEFAULT 'netload_forecast'::text NOT NULL,
    run_name text,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    mp_ids bigint[] NOT NULL,
    date_from date,
    date_to date,
    horizon_hours integer NOT NULL,
    test_fraction numeric NOT NULL,
    origin_step_h integer NOT NULL,
    feature_groups text[] NOT NULL,
    weather_source text DEFAULT 'forecast'::text NOT NULL,
    peak_threshold_kw numeric,
    models text[] NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    n_readings integer,
    n_train_rows integer,
    n_test_origins integer,
    n_test_days integer,
    best_model text,
    metrics jsonb,
    results jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT netload_forecast_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text]))),
    CONSTRAINT netload_forecast_run_weather CHECK ((weather_source = ANY (ARRAY['forecast'::text, 'actual'::text])))
);


--
-- Name: netload_forecast_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.netload_forecast_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.netload_forecast_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: netload_forecast_score; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.netload_forecast_score (
    run_id bigint NOT NULL,
    model text NOT NULL,
    n integer,
    mae numeric,
    rmse numeric,
    mape_pct numeric,
    bias numeric,
    pinball numeric,
    coverage_pct numeric,
    width_kw numeric,
    skill_mae_pct numeric,
    window_mae numeric,
    peak_mae_kw numeric,
    peak_bias_kw numeric,
    peak_time_mae_min numeric,
    exceed_brier numeric,
    exceed_auc numeric,
    exceed_recall numeric,
    exceed_precision numeric
);


--
-- Name: pcs_kpi; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.pcs_kpi (
    pcs_id bigint NOT NULL,
    kpi_date date NOT NULL,
    kpi_code text NOT NULL,
    kpi_name text NOT NULL,
    unit text,
    value numeric,
    sample_count integer NOT NULL,
    config_version integer NOT NULL,
    config_hash text NOT NULL,
    run_id bigint,
    calculated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE pcs_kpi; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.pcs_kpi IS 'Daily PCS KPIs per PCS unit, computed from pcs_telemetry by the definitions in kpi_config/pcs_kpi.yaml.';


--
-- Name: pcs_kpi_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.pcs_kpi_run (
    run_id bigint NOT NULL,
    status text NOT NULL,
    triggered_by text NOT NULL,
    pcs_ids bigint[],
    start_date date,
    end_date date,
    config_file text NOT NULL,
    config_version integer NOT NULL,
    config_hash text NOT NULL,
    kpi_codes text[] NOT NULL,
    systems_done integer,
    days integer,
    rows_deleted integer,
    rows_written integer,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT pcs_kpi_run_status_check CHECK ((status = ANY (ARRAY['running'::text, 'success'::text, 'failed'::text])))
);


--
-- Name: TABLE pcs_kpi_run; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON TABLE battery_ml.pcs_kpi_run IS 'One row per PCS KPI calculation (API button or CLI).';


--
-- Name: pcs_kpi_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.pcs_kpi_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.pcs_kpi_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: price_forecast_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.price_forecast_point (
    run_id bigint NOT NULL,
    ems_id bigint NOT NULL,
    origin_ts timestamp with time zone NOT NULL,
    target_ts timestamp with time zone NOT NULL,
    horizon_h smallint NOT NULL,
    model text NOT NULL,
    p10 real,
    p50 real,
    p90 real,
    mean real,
    spike_prob real,
    actual real
);


--
-- Name: price_forecast_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.price_forecast_run (
    run_id bigint NOT NULL,
    use_case text DEFAULT 'price_forecast'::text NOT NULL,
    run_name text,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    ems_ids bigint[] NOT NULL,
    date_from date,
    date_to date,
    resolution text DEFAULT 'hour'::text NOT NULL,
    horizon_hours integer NOT NULL,
    test_fraction numeric NOT NULL,
    origin_step_h integer NOT NULL,
    feature_groups text[] NOT NULL,
    models text[] NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    n_hours integer,
    n_train_rows integer,
    n_test_origins integer,
    n_spikes integer,
    best_model text,
    metrics jsonb,
    results jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT price_forecast_run_resolution CHECK ((resolution = ANY (ARRAY['hour'::text, '5min'::text]))),
    CONSTRAINT price_forecast_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: price_forecast_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.price_forecast_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.price_forecast_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: price_forecast_score; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.price_forecast_score (
    run_id bigint NOT NULL,
    model text NOT NULL,
    n integer,
    mae numeric,
    rmse numeric,
    smape_pct numeric,
    pinball numeric,
    coverage_pct numeric,
    width_mwh numeric,
    skill_mae_pct numeric,
    peak_mae numeric,
    spike_recall numeric,
    spike_precision numeric,
    spike_brier numeric,
    spread_capture_pct numeric
);


--
-- Name: rul_backtest; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.rul_backtest (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    snapshot_date date NOT NULL,
    method text NOT NULL,
    p10_days real,
    p50_days real,
    p90_days real,
    p50_cycles real,
    beyond boolean,
    actual_days real,
    actual_cycles real,
    known_alive_days real,
    censored boolean NOT NULL
);


--
-- Name: rul_forecast; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.rul_forecast (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    method text NOT NULL,
    as_of date NOT NULL,
    soh_pct real,
    resistance_ratio real,
    p10_days real,
    p50_days real,
    p90_days real,
    p10_cycles real,
    p50_cycles real,
    p90_cycles real,
    eol_date_p50 date,
    trigger text,
    beyond boolean
);


--
-- Name: rul_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.rul_run (
    run_id bigint NOT NULL,
    use_case text DEFAULT 'rul'::text NOT NULL,
    run_name text,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    system_ids bigint[] NOT NULL,
    methods text[] NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    n_units integer,
    n_rows integer,
    metrics jsonb,
    results jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT rul_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: rul_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.rul_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.rul_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: rul_score; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.rul_score (
    run_id bigint NOT NULL,
    method text NOT NULL,
    scope text NOT NULL,
    n integer,
    mae_days numeric,
    rmse_days numeric,
    bias_days numeric,
    mae_cycles numeric,
    coverage_pct numeric,
    pinball_days numeric,
    c_index numeric,
    censored_violation_pct numeric,
    oracle_mae_days numeric
);


--
-- Name: soc_estimation_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.soc_estimation_point (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    is_test boolean NOT NULL,
    truth real,
    anchor real,
    anchor_method text,
    coulomb real,
    ocv_lookup real,
    bms real,
    ekf real,
    ekf_p10 real,
    ekf_p90 real,
    gbm real,
    gbm_p10 real,
    gbm_p90 real,
    hybrid real,
    hybrid_p10 real,
    hybrid_p90 real,
    ekf_bias real,
    ekf_gain real,
    recal_kind text,
    at_rest boolean
);


--
-- Name: soc_estimation_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.soc_estimation_run (
    run_id bigint NOT NULL,
    use_case text DEFAULT 'soc_estimation'::text NOT NULL,
    run_name text,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    system_ids bigint[] NOT NULL,
    date_from date,
    date_to date,
    test_fraction numeric NOT NULL,
    label_source text NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    n_train_rows integer,
    n_test_rows integer,
    n_test_anchors integer,
    best_method text,
    primary_scope text,
    metrics jsonb,
    results jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT soc_estimation_run_label CHECK ((label_source = ANY (ARRAY['anchors'::text, 'dense'::text]))),
    CONSTRAINT soc_estimation_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: soc_estimation_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.soc_estimation_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.soc_estimation_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: soc_estimation_score; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.soc_estimation_score (
    run_id bigint NOT NULL,
    method text NOT NULL,
    scope text NOT NULL,
    n integer,
    rmse numeric,
    mae numeric,
    bias numeric,
    max_error numeric,
    p95_abs numeric,
    coverage_pct numeric,
    width numeric,
    skill_pct numeric
);


--
-- Name: soc_estimation_state; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.soc_estimation_state (
    run_id bigint NOT NULL,
    system_id bigint NOT NULL,
    state_ts timestamp with time zone NOT NULL,
    state jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: soc_forecast_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.soc_forecast_point (
    run_id bigint NOT NULL,
    ems_id bigint NOT NULL,
    origin_ts timestamp with time zone NOT NULL,
    step smallint NOT NULL,
    method text NOT NULL,
    p10 real,
    p50 real,
    p90 real,
    actual real,
    plan_kw real
);


--
-- Name: soc_forecast_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.soc_forecast_run (
    run_id bigint NOT NULL,
    use_case text DEFAULT 'soc_forecast'::text NOT NULL,
    run_name text,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    ems_ids bigint[] NOT NULL,
    date_from date,
    date_to date,
    horizon_h numeric NOT NULL,
    test_fraction numeric NOT NULL,
    origin_step_min integer NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    n_train_rows integer,
    n_test_origins integer,
    best_method text,
    metrics jsonb,
    results jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT soc_forecast_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: soc_forecast_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.soc_forecast_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.soc_forecast_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: soc_forecast_score; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.soc_forecast_score (
    run_id bigint NOT NULL,
    method text NOT NULL,
    n integer,
    mae numeric,
    rmse numeric,
    mae_1h numeric,
    mae_4h numeric,
    mae_end numeric,
    max_error numeric,
    coverage_pct numeric,
    width numeric,
    skill_pct numeric,
    drawdown_mae numeric,
    breach_pct numeric
);


--
-- Name: thermal_forecast_point; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.thermal_forecast_point (
    run_id bigint NOT NULL,
    target text NOT NULL,
    system_id bigint NOT NULL,
    origin_ts timestamp with time zone NOT NULL,
    horizon_min smallint NOT NULL,
    method text NOT NULL,
    p10 real,
    p50 real,
    p90 real,
    actual real,
    now_c real
);


--
-- Name: thermal_forecast_run; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.thermal_forecast_run (
    run_id bigint NOT NULL,
    use_case text DEFAULT 'thermal_forecast'::text NOT NULL,
    run_name text,
    status text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    system_ids bigint[] NOT NULL,
    date_from date,
    date_to date,
    targets text[] NOT NULL,
    horizons_min integer[] NOT NULL,
    test_fraction numeric NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    n_train_rows integer,
    n_test_rows integer,
    metrics jsonb,
    results jsonb,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    CONSTRAINT thermal_forecast_run_status CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text])))
);


--
-- Name: thermal_forecast_run_run_id_seq; Type: SEQUENCE; Schema: battery_ml; Owner: -
--

ALTER TABLE battery_ml.thermal_forecast_run ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_ml.thermal_forecast_run_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: thermal_forecast_score; Type: TABLE; Schema: battery_ml; Owner: -
--

CREATE TABLE battery_ml.thermal_forecast_score (
    run_id bigint NOT NULL,
    target text NOT NULL,
    horizon_min integer NOT NULL,
    method text NOT NULL,
    n integer,
    mae numeric,
    rmse numeric,
    pinball numeric,
    coverage_pct numeric,
    threshold_c numeric,
    events integer,
    recall_p50 numeric,
    precision_p50 numeric,
    recall_p90 numeric,
    precision_p90 numeric
);


--
-- Name: v_heatload_daily; Type: VIEW; Schema: battery_ml; Owner: -
--

CREATE VIEW battery_ml.v_heatload_daily AS
 SELECT run_id,
    system_id,
    public.time_bucket('1 day'::interval, ts, 'Asia/Kolkata'::text) AS day,
    count(*) AS intervals,
    max(q_total_kw) AS q_total_peak_kw,
    avg(q_total_kw) AS q_total_mean_kw,
    max(q_model_kw) AS q_model_peak_kw,
    max(measured_kw) AS measured_peak_kw,
    avg(measured_kw) AS measured_mean_kw,
    (sum(q_total_kw) / 12.0) AS q_total_kwh,
    (sum(measured_kw) / 12.0) AS measured_kwh,
    avg(q_batt_irr_kw) AS q_batt_irr_mean_kw,
    avg(q_batt_rev_kw) AS q_batt_rev_mean_kw,
    avg(q_pcs_kw) AS q_pcs_mean_kw,
    avg(q_aux_kw) AS q_aux_mean_kw,
    avg(q_solar_kw) AS q_solar_mean_kw,
    avg(q_env_kw) AS q_env_mean_kw,
    avg(residual_kw) AS residual_mean_kw,
    max(t_amb_c) AS t_amb_max_c,
    max(dt_cell_c) AS dt_cell_max_c
   FROM battery_ml.heatload_ledger
  GROUP BY run_id, system_id, (public.time_bucket('1 day'::interval, ts, 'Asia/Kolkata'::text));


--
-- Name: v_hvac_cop_daily; Type: VIEW; Schema: battery_ml; Owner: -
--

CREATE VIEW battery_ml.v_hvac_cop_daily AS
 SELECT run_id,
    hvac_id,
    public.time_bucket('1 day'::interval, ts, 'Asia/Kolkata'::text) AS day,
    count(*) FILTER (WHERE (mode = 'COOLING'::text)) AS cooling_intervals,
    count(*) FILTER (WHERE steady) AS steady_intervals,
    (sum(cap_actual_kw) FILTER (WHERE (mode = 'COOLING'::text)) / NULLIF(sum(power_kw) FILTER (WHERE (mode = 'COOLING'::text)), (0)::numeric)) AS weighted_cop,
    (sum(power_kw) FILTER (WHERE (mode = 'COOLING'::text)) / NULLIF((sum(cap_actual_kw) FILTER (WHERE (mode = 'COOLING'::text)) / 3.517), (0)::numeric)) AS kw_per_ton,
    avg(cop_residual) FILTER (WHERE steady) AS residual_mean,
    avg(eta_2nd_law) FILTER (WHERE steady) AS eta_2nd_law_mean,
    avg(cop_actual) FILTER (WHERE steady) AS cop_mean,
    avg(cop_expected) FILTER (WHERE steady) AS cop_expected_mean,
    max(t_amb_c) AS t_amb_max_c
   FROM battery_ml.hvac_cop_point
  GROUP BY run_id, hvac_id, (public.time_bucket('1 day'::interval, ts, 'Asia/Kolkata'::text));


--
-- Name: v_mv_anomaly_alarm; Type: VIEW; Schema: battery_ml; Owner: -
--

CREATE VIEW battery_ml.v_mv_anomaly_alarm AS
 SELECT s.run_id,
    s.system_id,
    s.ts,
    s.split,
    s.regime,
    s.anomaly_score,
    s.score_smooth,
    s.model_flag,
    s.is_anomaly,
    s.rule_flags,
    s.models_flagging,
    s.top_contributors,
    (a.alarm_count > 0) AS alarm_active,
    COALESCE(a.alarm_count, (0)::bigint) AS alarm_count,
    a.alarm_codes,
    a.alarm_sources,
    a.max_severity
   FROM (battery_ml.mv_anomaly_score s
     LEFT JOIN LATERAL ( SELECT count(*) AS alarm_count,
            array_agg(DISTINCT c.alarm_code) AS alarm_codes,
            array_agg(DISTINCT c.source) AS alarm_sources,
            max(e.severity_level) AS max_severity
           FROM (battery_telemetry.alarm_event e
             LEFT JOIN battery_master.alarm_catalog c ON ((c.alarm_catalog_id = e.alarm_catalog_id)))
          WHERE ((e.battery_system_id = s.system_id) AND (e."time" <= s.ts) AND (s.ts < COALESCE(e.end_time, (e."time" + '00:30:00'::interval))))) a ON (true));


--
-- Name: VIEW v_mv_anomaly_alarm; Type: COMMENT; Schema: battery_ml; Owner: -
--

COMMENT ON VIEW battery_ml.v_mv_anomaly_alarm IS 'Multivariate anomaly scores with the alarm_event rows active at each interval - for evaluation and explanation.';


--
-- Name: bak_20261015_aging_snapshot; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.bak_20261015_aging_snapshot (
    system_id bigint,
    snapshot_date date,
    age_days integer,
    calendar_age_years numeric(6,2),
    cum_throughput_mwh numeric(12,1),
    equiv_full_cycles numeric(10,1),
    avg_dod_pct numeric(5,1),
    avg_cell_temp_c numeric(5,1),
    days_at_high_soc numeric(6,1),
    soh_pct numeric(5,2),
    internal_resistance_mohm numeric(8,3),
    rul_cycles numeric(10,1),
    rul_days integer,
    is_censored boolean,
    eol_reached boolean
);


--
-- Name: bak_20261015_battery_provenance; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.bak_20261015_battery_provenance (
    system_id bigint,
    manufacturer text,
    cell_model text,
    chemistry text,
    batch_lot text,
    cell_format text,
    build_date date,
    nameplate_kwh numeric(10,2),
    bol_capacity_kwh numeric(10,2),
    bol_resistance_mohm numeric(8,3),
    usage_cycles_per_day numeric(5,2),
    climate_avg_temp_c numeric(5,2)
);


--
-- Name: bak_20261015_bess_system; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.bak_20261015_bess_system (
    system_id bigint,
    system_code text
);


--
-- Name: bak_20261015_capacity_test; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.bak_20261015_capacity_test (
    test_id bigint,
    system_id bigint,
    test_date date,
    age_days integer,
    equiv_full_cycles numeric(10,1),
    measured_capacity_kwh numeric(10,2),
    soh_pct numeric(5,2),
    internal_resistance_mohm numeric(8,3),
    test_temp_c numeric(5,2),
    method text
);


--
-- Name: bak_20261015_lifecycle_event; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.bak_20261015_lifecycle_event (
    event_id bigint,
    system_id bigint,
    event_type text,
    event_date date,
    age_days integer,
    soh_at_event numeric(5,2),
    failure_mode text,
    note text
);


--
-- Name: bak_20261015_rul_backtest; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.bak_20261015_rul_backtest (
    run_id bigint,
    system_id bigint,
    snapshot_date date,
    method text,
    p10_days real,
    p50_days real,
    p90_days real,
    p50_cycles real,
    beyond boolean,
    actual_days real,
    actual_cycles real,
    known_alive_days real,
    censored boolean
);


--
-- Name: bak_20261015_rul_forecast; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.bak_20261015_rul_forecast (
    run_id bigint,
    system_id bigint,
    method text,
    as_of date,
    soh_pct real,
    resistance_ratio real,
    p10_days real,
    p50_days real,
    p90_days real,
    p10_cycles real,
    p50_cycles real,
    p90_cycles real,
    eol_date_p50 date,
    trigger text,
    beyond boolean
);


--
-- Name: bak_20261015_rul_run; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.bak_20261015_rul_run (
    run_id bigint,
    use_case text,
    run_name text,
    status text,
    is_default boolean,
    system_ids bigint[],
    methods text[],
    params jsonb,
    n_units integer,
    n_rows integer,
    metrics jsonb,
    results jsonb,
    warnings jsonb,
    error_message text,
    artifact_path text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    duration_ms integer
);


--
-- Name: bak_20261015_rul_score; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.bak_20261015_rul_score (
    run_id bigint,
    method text,
    scope text,
    n integer,
    mae_days numeric,
    rmse_days numeric,
    bias_days numeric,
    mae_cycles numeric,
    coverage_pct numeric,
    pinball_days numeric,
    c_index numeric,
    censored_violation_pct numeric,
    oracle_mae_days numeric
);


--
-- Name: batchlog; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.batchlog (
    batch_id bigint NOT NULL,
    run_id uuid NOT NULL,
    job_name text DEFAULT 'realtime_snapshot'::text NOT NULL,
    file_name text NOT NULL,
    file_time timestamp with time zone,
    snapshot_time timestamp with time zone,
    status text NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone NOT NULL,
    duration_ms integer NOT NULL,
    feeds_total integer DEFAULT 0 NOT NULL,
    feeds_loaded integer DEFAULT 0 NOT NULL,
    feeds_failed integer DEFAULT 0 NOT NULL,
    rows_total integer DEFAULT 0 NOT NULL,
    rows_inserted integer DEFAULT 0 NOT NULL,
    rows_updated integer DEFAULT 0 NOT NULL,
    rows_skipped integer DEFAULT 0 NOT NULL,
    feed_results jsonb DEFAULT '[]'::jsonb NOT NULL,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    id_changes jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    archive_path text,
    api_url text,
    host_name text,
    report jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT batchlog_rows CHECK ((((rows_inserted + rows_updated) + rows_skipped) <= rows_total)),
    CONSTRAINT batchlog_status CHECK ((status = ANY (ARRAY['SUCCESS'::text, 'PARTIAL'::text, 'FAILED'::text]))),
    CONSTRAINT batchlog_times CHECK ((finished_at >= started_at))
);


--
-- Name: TABLE batchlog; Type: COMMENT; Schema: battery_raw; Owner: -
--

COMMENT ON TABLE battery_raw.batchlog IS 'Load reports of the realtime snapshot batch: one row per input file processed';


--
-- Name: batchlog_batch_id_seq; Type: SEQUENCE; Schema: battery_raw; Owner: -
--

ALTER TABLE battery_raw.batchlog ALTER COLUMN batch_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_raw.batchlog_batch_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: soc_estimation_data; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.soc_estimation_data (
    stg_id bigint NOT NULL,
    system_name text NOT NULL,
    ts timestamp without time zone,
    true_current_a numeric,
    measured_current_a numeric,
    current_sensor_offset_a numeric,
    soc_true_pct numeric,
    soc_coulomb_pct numeric,
    soc_bms_pct numeric,
    usable_capacity_ah numeric,
    coulombic_efficiency numeric,
    at_rest boolean,
    rest_duration_min numeric,
    ocv_rested_v numeric,
    source_file text NOT NULL,
    row_no integer NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE soc_estimation_data; Type: COMMENT; Schema: battery_raw; Owner: -
--

COMMENT ON TABLE battery_raw.soc_estimation_data IS 'Staging copy of soc_estimation_data CSV files, as is; used to UPDATE system_telemetry SOC-estimation columns.';


--
-- Name: soc_estimation_data_stg_id_seq; Type: SEQUENCE; Schema: battery_raw; Owner: -
--

ALTER TABLE battery_raw.soc_estimation_data ALTER COLUMN stg_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_raw.soc_estimation_data_stg_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: soc_stg; Type: TABLE; Schema: battery_raw; Owner: -
--

CREATE TABLE battery_raw.soc_stg (
    stg_id bigint NOT NULL,
    system_code text,
    ts timestamp without time zone,
    soc_true_pct numeric,
    method text,
    note text,
    source_file text NOT NULL,
    row_no integer NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE soc_stg; Type: COMMENT; Schema: battery_raw; Owner: -
--

COMMENT ON TABLE battery_raw.soc_stg IS 'Staging copy of soc_reference CSV files, as is (no mapping / validation); reloading a file replaces its rows.';


--
-- Name: soc_stg_stg_id_seq; Type: SEQUENCE; Schema: battery_raw; Owner: -
--

ALTER TABLE battery_raw.soc_stg ALTER COLUMN stg_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_raw.soc_stg_stg_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


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
-- Name: access_request; Type: TABLE; Schema: battery_users; Owner: -
--

CREATE TABLE battery_users.access_request (
    request_id bigint NOT NULL,
    full_name text NOT NULL,
    email character varying(320) NOT NULL,
    organisation text,
    reason text NOT NULL,
    hashed_password character varying(1024) NOT NULL,
    status text DEFAULT 'PENDING'::text NOT NULL,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    request_ip text,
    reviewed_at timestamp with time zone,
    reviewed_by text,
    role_id smallint,
    tenant_id bigint,
    decision_note text,
    user_id uuid,
    CONSTRAINT access_request_status_check CHECK ((status = ANY (ARRAY['PENDING'::text, 'APPROVED'::text, 'REJECTED'::text])))
);


--
-- Name: access_request_request_id_seq; Type: SEQUENCE; Schema: battery_users; Owner: -
--

ALTER TABLE battery_users.access_request ALTER COLUMN request_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_users.access_request_request_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: app_user; Type: TABLE; Schema: battery_users; Owner: -
--

CREATE TABLE battery_users.app_user (
    id uuid NOT NULL,
    email character varying(320) NOT NULL,
    hashed_password character varying(1024) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    is_superuser boolean DEFAULT false NOT NULL,
    is_verified boolean DEFAULT true NOT NULL,
    full_name text,
    role_id smallint NOT NULL,
    tenant_id bigint,
    is_service_account boolean DEFAULT false NOT NULL,
    must_change_password boolean DEFAULT true NOT NULL,
    failed_logins integer DEFAULT 0 NOT NULL,
    locked_until timestamp with time zone,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: auth_audit; Type: TABLE; Schema: battery_users; Owner: -
--

CREATE TABLE battery_users.auth_audit (
    audit_id bigint NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    user_id uuid,
    email text,
    event text NOT NULL,
    success boolean NOT NULL,
    ip text,
    user_agent text,
    detail jsonb
);


--
-- Name: auth_audit_audit_id_seq; Type: SEQUENCE; Schema: battery_users; Owner: -
--

ALTER TABLE battery_users.auth_audit ALTER COLUMN audit_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_users.auth_audit_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: privilege; Type: TABLE; Schema: battery_users; Owner: -
--

CREATE TABLE battery_users.privilege (
    privilege_id integer NOT NULL,
    resource text NOT NULL,
    action text NOT NULL,
    code text GENERATED ALWAYS AS (((resource || ':'::text) || action)) STORED,
    module_label text,
    CONSTRAINT privilege_action_check CHECK ((action = ANY (ARRAY['read'::text, 'write'::text, 'delete'::text, 'execute'::text, 'approve'::text])))
);


--
-- Name: privilege_privilege_id_seq; Type: SEQUENCE; Schema: battery_users; Owner: -
--

ALTER TABLE battery_users.privilege ALTER COLUMN privilege_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_users.privilege_privilege_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: refresh_token; Type: TABLE; Schema: battery_users; Owner: -
--

CREATE TABLE battery_users.refresh_token (
    token_id uuid NOT NULL,
    user_id uuid NOT NULL,
    family_id uuid NOT NULL,
    token_hash text NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    replaced_by uuid,
    user_agent text,
    ip text
);


--
-- Name: role; Type: TABLE; Schema: battery_users; Owner: -
--

CREATE TABLE battery_users.role (
    role_id smallint NOT NULL,
    role_code text NOT NULL,
    role_name text NOT NULL,
    is_tenant_scoped boolean DEFAULT false NOT NULL,
    description text
);


--
-- Name: role_privilege; Type: TABLE; Schema: battery_users; Owner: -
--

CREATE TABLE battery_users.role_privilege (
    role_id smallint NOT NULL,
    privilege_id integer NOT NULL
);


--
-- Name: role_role_id_seq; Type: SEQUENCE; Schema: battery_users; Owner: -
--

ALTER TABLE battery_users.role ALTER COLUMN role_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME battery_users.role_role_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: v_role_permissions; Type: VIEW; Schema: battery_users; Owner: -
--

CREATE VIEW battery_users.v_role_permissions AS
 SELECT r.role_code,
    r.role_name,
    p.resource,
    p.action,
    p.code,
    p.module_label
   FROM ((battery_users.role r
     JOIN battery_users.role_privilege rp ON ((rp.role_id = r.role_id)))
     JOIN battery_users.privilege p ON ((p.privilege_id = rp.privilege_id)));


--
-- Name: activity_log activity_log_pkey; Type: CONSTRAINT; Schema: battery_itops; Owner: -
--

ALTER TABLE ONLY battery_itops.activity_log
    ADD CONSTRAINT activity_log_pkey PRIMARY KEY (activity_id);


--
-- Name: alarm_catalog alarm_catalog_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.alarm_catalog
    ADD CONSTRAINT alarm_catalog_pkey PRIMARY KEY (alarm_catalog_id);


--
-- Name: alarm_catalog alarm_catalog_source_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.alarm_catalog
    ADD CONSTRAINT alarm_catalog_source_code_key UNIQUE (source, alarm_code);


--
-- Name: alarm_severity alarm_severity_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.alarm_severity
    ADD CONSTRAINT alarm_severity_pkey PRIMARY KEY (severity_level);


--
-- Name: alarm_severity alarm_severity_severity_name_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.alarm_severity
    ADD CONSTRAINT alarm_severity_severity_name_key UNIQUE (severity_name);


--
-- Name: as_award as_award_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.as_award
    ADD CONSTRAINT as_award_pkey PRIMARY KEY (award_id);


--
-- Name: as_product as_product_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.as_product
    ADD CONSTRAINT as_product_pkey PRIMARY KEY (product_id);


--
-- Name: as_product as_product_product_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.as_product
    ADD CONSTRAINT as_product_product_code_key UNIQUE (product_code);


--
-- Name: asset_hierarchy asset_hierarchy_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.asset_hierarchy
    ADD CONSTRAINT asset_hierarchy_pkey PRIMARY KEY (asset_id);


--
-- Name: asset_hierarchy asset_hierarchy_source_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.asset_hierarchy
    ADD CONSTRAINT asset_hierarchy_source_key UNIQUE (asset_type, source_id);


--
-- Name: battery_chemistry battery_chemistry_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_chemistry
    ADD CONSTRAINT battery_chemistry_pkey PRIMARY KEY (chemistry_code);


--
-- Name: battery_container battery_container_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_container
    ADD CONSTRAINT battery_container_pkey PRIMARY KEY (container_id);


--
-- Name: battery_container battery_container_source_uuid_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_container
    ADD CONSTRAINT battery_container_source_uuid_key UNIQUE (source_uuid);


--
-- Name: battery_module battery_module_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_module
    ADD CONSTRAINT battery_module_pkey PRIMARY KEY (module_id);


--
-- Name: battery_module battery_module_serial_number_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_module
    ADD CONSTRAINT battery_module_serial_number_key UNIQUE (serial_number);


--
-- Name: battery_module battery_module_source_uuid_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_module
    ADD CONSTRAINT battery_module_source_uuid_key UNIQUE (source_uuid);


--
-- Name: battery_opt_param battery_opt_param_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_opt_param
    ADD CONSTRAINT battery_opt_param_pkey PRIMARY KEY (param_id);


--
-- Name: battery_pack battery_pack_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_pack
    ADD CONSTRAINT battery_pack_pkey PRIMARY KEY (pack_id);


--
-- Name: battery_pack battery_pack_source_uuid_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_pack
    ADD CONSTRAINT battery_pack_source_uuid_key UNIQUE (source_uuid);


--
-- Name: battery_provenance battery_provenance_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_provenance
    ADD CONSTRAINT battery_provenance_pkey PRIMARY KEY (system_id);


--
-- Name: battery_system battery_system_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_system
    ADD CONSTRAINT battery_system_pkey PRIMARY KEY (battery_system_id);


--
-- Name: battery_system battery_system_source_uuid_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_system
    ADD CONSTRAINT battery_system_source_uuid_key UNIQUE (source_uuid);


--
-- Name: calendar_day calendar_day_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.calendar_day
    ADD CONSTRAINT calendar_day_pkey PRIMARY KEY (calendar_date);


--
-- Name: capacity_test capacity_test_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.capacity_test
    ADD CONSTRAINT capacity_test_pkey PRIMARY KEY (test_id);


--
-- Name: contactor_state contactor_state_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.contactor_state
    ADD CONSTRAINT contactor_state_pkey PRIMARY KEY (state_code);


--
-- Name: current_sensor_cal current_sensor_cal_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.current_sensor_cal
    ADD CONSTRAINT current_sensor_cal_pkey PRIMARY KEY (system_id, calibrated_on);


--
-- Name: decision_state decision_state_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.decision_state
    ADD CONSTRAINT decision_state_pkey PRIMARY KEY (run_id);


--
-- Name: demand_tariff demand_tariff_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.demand_tariff
    ADD CONSTRAINT demand_tariff_pkey PRIMARY KEY (tariff_id);


--
-- Name: ems_controller ems_controller_ems_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.ems_controller
    ADD CONSTRAINT ems_controller_ems_code_key UNIQUE (ems_code);


--
-- Name: ems_controller ems_controller_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.ems_controller
    ADD CONSTRAINT ems_controller_pkey PRIMARY KEY (ems_id);


--
-- Name: ems_controller ems_controller_source_uuid_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.ems_controller
    ADD CONSTRAINT ems_controller_source_uuid_key UNIQUE (source_uuid);


--
-- Name: ems_dispatch_mode ems_dispatch_mode_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.ems_dispatch_mode
    ADD CONSTRAINT ems_dispatch_mode_pkey PRIMARY KEY (mode_code);


--
-- Name: ems_grid_service ems_grid_service_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.ems_grid_service
    ADD CONSTRAINT ems_grid_service_pkey PRIMARY KEY (service_code);


--
-- Name: ems_tariff_period ems_tariff_period_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.ems_tariff_period
    ADD CONSTRAINT ems_tariff_period_pkey PRIMARY KEY (tariff_period_id);


--
-- Name: eol_criteria eol_criteria_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.eol_criteria
    ADD CONSTRAINT eol_criteria_pkey PRIMARY KEY (chemistry);


--
-- Name: fault_alarm_link fault_alarm_link_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_alarm_link
    ADD CONSTRAINT fault_alarm_link_pkey PRIMARY KEY (episode_id, alarm_id);


--
-- Name: fault_catalog fault_catalog_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_catalog
    ADD CONSTRAINT fault_catalog_pkey PRIMARY KEY (fault_code);


--
-- Name: fault_catalog fault_catalog_subsystem_check; Type: CHECK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE battery_master.fault_catalog
    ADD CONSTRAINT fault_catalog_subsystem_check CHECK ((subsystem = ANY (ARRAY['BMS'::text, 'PCS'::text, 'EMS'::text, 'HVAC'::text, 'PLANT'::text]))) NOT VALID;


--
-- Name: fault_episode fault_episode_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_episode
    ADD CONSTRAINT fault_episode_pkey PRIMARY KEY (episode_id);


--
-- Name: fault_prediction fault_prediction_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_prediction
    ADD CONSTRAINT fault_prediction_pkey PRIMARY KEY (prediction_id);


--
-- Name: fault_signature fault_signature_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_signature
    ADD CONSTRAINT fault_signature_pkey PRIMARY KEY (signature_id);


--
-- Name: generation_asset generation_asset_gen_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.generation_asset
    ADD CONSTRAINT generation_asset_gen_code_key UNIQUE (gen_code);


--
-- Name: generation_asset generation_asset_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.generation_asset
    ADD CONSTRAINT generation_asset_pkey PRIMARY KEY (gen_id);


--
-- Name: grid_charge grid_charge_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.grid_charge
    ADD CONSTRAINT grid_charge_pkey PRIMARY KEY (charge_id);


--
-- Name: hvac_cooling_mode hvac_cooling_mode_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.hvac_cooling_mode
    ADD CONSTRAINT hvac_cooling_mode_pkey PRIMARY KEY (mode_code);


--
-- Name: hvac_unit hvac_unit_hvac_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.hvac_unit
    ADD CONSTRAINT hvac_unit_hvac_code_key UNIQUE (hvac_code);


--
-- Name: hvac_unit hvac_unit_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.hvac_unit
    ADD CONSTRAINT hvac_unit_pkey PRIMARY KEY (hvac_id);


--
-- Name: hvac_unit hvac_unit_source_uuid_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.hvac_unit
    ADD CONSTRAINT hvac_unit_source_uuid_key UNIQUE (source_uuid);


--
-- Name: lifecycle_event lifecycle_event_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.lifecycle_event
    ADD CONSTRAINT lifecycle_event_pkey PRIMARY KEY (event_id);


--
-- Name: maintenance_action maintenance_action_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.maintenance_action
    ADD CONSTRAINT maintenance_action_pkey PRIMARY KEY (action_id);


--
-- Name: market market_market_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.market
    ADD CONSTRAINT market_market_code_key UNIQUE (market_code);


--
-- Name: market market_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.market
    ADD CONSTRAINT market_pkey PRIMARY KEY (market_id);


--
-- Name: metering_point metering_point_mp_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.metering_point
    ADD CONSTRAINT metering_point_mp_code_key UNIQUE (mp_code);


--
-- Name: metering_point metering_point_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.metering_point
    ADD CONSTRAINT metering_point_pkey PRIMARY KEY (metering_point_id);


--
-- Name: ocv_curve ocv_curve_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.ocv_curve
    ADD CONSTRAINT ocv_curve_pkey PRIMARY KEY (chemistry, direction, temp_c, soc_pct);


--
-- Name: operating_mode operating_mode_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.operating_mode
    ADD CONSTRAINT operating_mode_pkey PRIMARY KEY (mode_code);


--
-- Name: optimization_run optimization_run_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.optimization_run
    ADD CONSTRAINT optimization_run_pkey PRIMARY KEY (run_id);


--
-- Name: pcs_alarm_type pcs_alarm_type_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs_alarm_type
    ADD CONSTRAINT pcs_alarm_type_pkey PRIMARY KEY (alarm_type_code);


--
-- Name: pcs_breaker_state pcs_breaker_state_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs_breaker_state
    ADD CONSTRAINT pcs_breaker_state_pkey PRIMARY KEY (state_code);


--
-- Name: pcs_command_type pcs_command_type_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs_command_type
    ADD CONSTRAINT pcs_command_type_pkey PRIMARY KEY (command_code);


--
-- Name: pcs_grid_service pcs_grid_service_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs_grid_service
    ADD CONSTRAINT pcs_grid_service_pkey PRIMARY KEY (service_code);


--
-- Name: pcs_mode pcs_mode_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs_mode
    ADD CONSTRAINT pcs_mode_pkey PRIMARY KEY (mode_code);


--
-- Name: pcs pcs_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs
    ADD CONSTRAINT pcs_pkey PRIMARY KEY (pcs_id);


--
-- Name: pcs_ride_through_type pcs_ride_through_type_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs_ride_through_type
    ADD CONSTRAINT pcs_ride_through_type_pkey PRIMARY KEY (rt_code);


--
-- Name: pcs pcs_source_uuid_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs
    ADD CONSTRAINT pcs_source_uuid_key UNIQUE (source_uuid);


--
-- Name: pcs pcs_system_id_pcs_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs
    ADD CONSTRAINT pcs_system_id_pcs_code_key UNIQUE (system_id, pcs_code);


--
-- Name: aging_snapshot pk_aging_snapshot; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.aging_snapshot
    ADD CONSTRAINT pk_aging_snapshot PRIMARY KEY (system_id, snapshot_date);


--
-- Name: as_price pk_as_price; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.as_price
    ADD CONSTRAINT pk_as_price PRIMARY KEY (product_id, delivery_start);


--
-- Name: dam_price pk_dam_price; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.dam_price
    ADD CONSTRAINT pk_dam_price PRIMARY KEY (node_id, delivery_start);


--
-- Name: degradation_cost_curve pk_degr_curve; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.degradation_cost_curve
    ADD CONSTRAINT pk_degr_curve PRIMARY KEY (system_id, dod_band_pct);


--
-- Name: dispatch_outcome pk_dispatch_outcome; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.dispatch_outcome
    ADD CONSTRAINT pk_dispatch_outcome PRIMARY KEY (system_id, interval_start);


--
-- Name: dispatch_schedule pk_dispatch_schedule; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.dispatch_schedule
    ADD CONSTRAINT pk_dispatch_schedule PRIMARY KEY (run_id, interval_start);


--
-- Name: efficiency_curve pk_eff_curve; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.efficiency_curve
    ADD CONSTRAINT pk_eff_curve PRIMARY KEY (system_id, direction, power_fraction, soc_band);


--
-- Name: interconnection_limit pk_poi_limit; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.interconnection_limit
    ADD CONSTRAINT pk_poi_limit PRIMARY KEY (system_id, valid_from);


--
-- Name: price_forecast pk_price_forecast; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.price_forecast
    ADD CONSTRAINT pk_price_forecast PRIMARY KEY (node_id, issued_at, target_ts);


--
-- Name: price_scenario pk_price_scenario; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.price_scenario
    ADD CONSTRAINT pk_price_scenario PRIMARY KEY (node_id, issued_at, scenario_id, target_ts);


--
-- Name: rt_price pk_rt_price; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.rt_price
    ADD CONSTRAINT pk_rt_price PRIMARY KEY (node_id, interval_start);


--
-- Name: price_node price_node_node_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.price_node
    ADD CONSTRAINT price_node_node_code_key UNIQUE (node_code);


--
-- Name: price_node price_node_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.price_node
    ADD CONSTRAINT price_node_pkey PRIMARY KEY (node_id);


--
-- Name: site site_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.site
    ADD CONSTRAINT site_pkey PRIMARY KEY (site_id);


--
-- Name: site site_site_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.site
    ADD CONSTRAINT site_site_code_key UNIQUE (site_code);


--
-- Name: site site_source_uuid_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.site
    ADD CONSTRAINT site_source_uuid_key UNIQUE (source_uuid);


--
-- Name: soc_reference soc_reference_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.soc_reference
    ADD CONSTRAINT soc_reference_pkey PRIMARY KEY (system_id, ts);


--
-- Name: tenant_contact tenant_contact_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.tenant_contact
    ADD CONSTRAINT tenant_contact_pkey PRIMARY KEY (contact_id);


--
-- Name: tenant tenant_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.tenant
    ADD CONSTRAINT tenant_pkey PRIMARY KEY (tenant_id);


--
-- Name: tenant_site tenant_site_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.tenant_site
    ADD CONSTRAINT tenant_site_pkey PRIMARY KEY (tenant_id, site_id);


--
-- Name: tenant tenant_source_uuid_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.tenant
    ADD CONSTRAINT tenant_source_uuid_key UNIQUE (source_uuid);


--
-- Name: transformer transformer_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.transformer
    ADD CONSTRAINT transformer_pkey PRIMARY KEY (transformer_id);


--
-- Name: as_award uq_as_award_slot; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.as_award
    ADD CONSTRAINT uq_as_award_slot UNIQUE (system_id, product_id, delivery_start);


--
-- Name: battery_opt_param uq_optparam; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_opt_param
    ADD CONSTRAINT uq_optparam UNIQUE (system_id, valid_from);


--
-- Name: weather_station weather_station_pkey; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.weather_station
    ADD CONSTRAINT weather_station_pkey PRIMARY KEY (station_id);


--
-- Name: weather_station weather_station_station_code_key; Type: CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.weather_station
    ADD CONSTRAINT weather_station_station_code_key UNIQUE (station_code);


--
-- Name: anomaly_module_result anomaly_module_result_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.anomaly_module_result
    ADD CONSTRAINT anomaly_module_result_pkey PRIMARY KEY (run_id, module_id);


--
-- Name: anomaly_point anomaly_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.anomaly_point
    ADD CONSTRAINT anomaly_point_pkey PRIMARY KEY (run_id, module_id, bucket);


--
-- Name: anomaly_run anomaly_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.anomaly_run
    ADD CONSTRAINT anomaly_run_pkey PRIMARY KEY (run_id);


--
-- Name: arb_backtest arb_backtest_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.arb_backtest
    ADD CONSTRAINT arb_backtest_pkey PRIMARY KEY (study_id, kind, interval_start);


--
-- Name: arb_study_day arb_study_day_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.arb_study_day
    ADD CONSTRAINT arb_study_day_pkey PRIMARY KEY (study_id, kpi_date);


--
-- Name: arb_study arb_study_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.arb_study
    ADD CONSTRAINT arb_study_pkey PRIMARY KEY (study_id);


--
-- Name: aux_forecast_daily aux_forecast_daily_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.aux_forecast_daily
    ADD CONSTRAINT aux_forecast_daily_pkey PRIMARY KEY (run_id, ems_id, day, method);


--
-- Name: aux_forecast_point aux_forecast_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.aux_forecast_point
    ADD CONSTRAINT aux_forecast_point_pkey PRIMARY KEY (run_id, ems_id, origin_ts, horizon_min, method);


--
-- Name: aux_forecast_run aux_forecast_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.aux_forecast_run
    ADD CONSTRAINT aux_forecast_run_pkey PRIMARY KEY (run_id);


--
-- Name: aux_forecast_score aux_forecast_score_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.aux_forecast_score
    ADD CONSTRAINT aux_forecast_score_pkey PRIMARY KEY (run_id, ems_id, horizon_bucket, method);


--
-- Name: bms_kpi bms_kpi_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.bms_kpi
    ADD CONSTRAINT bms_kpi_pkey PRIMARY KEY (system_id, kpi_date, kpi_code);


--
-- Name: bms_kpi_run bms_kpi_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.bms_kpi_run
    ADD CONSTRAINT bms_kpi_run_pkey PRIMARY KEY (run_id);


--
-- Name: efficiency_cycle efficiency_cycle_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.efficiency_cycle
    ADD CONSTRAINT efficiency_cycle_pkey PRIMARY KEY (run_id, cycle_no);


--
-- Name: efficiency_run efficiency_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.efficiency_run
    ADD CONSTRAINT efficiency_run_pkey PRIMARY KEY (run_id);


--
-- Name: efficiency_score efficiency_score_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.efficiency_score
    ADD CONSTRAINT efficiency_score_pkey PRIMARY KEY (run_id, model, dataset);


--
-- Name: ems_kpi ems_kpi_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.ems_kpi
    ADD CONSTRAINT ems_kpi_pkey PRIMARY KEY (ems_id, kpi_date, kpi_code);


--
-- Name: ems_kpi_run ems_kpi_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.ems_kpi_run
    ADD CONSTRAINT ems_kpi_run_pkey PRIMARY KEY (run_id);


--
-- Name: fault_diag_candidate fault_diag_candidate_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_candidate
    ADD CONSTRAINT fault_diag_candidate_pkey PRIMARY KEY (candidate_id);


--
-- Name: fault_diag_candidate fault_diag_candidate_run_id_system_id_peak_ts_fault_code_key; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_candidate
    ADD CONSTRAINT fault_diag_candidate_run_id_system_id_peak_ts_fault_code_key UNIQUE (run_id, system_id, peak_ts, fault_code);


--
-- Name: fault_diag_example fault_diag_example_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_example
    ADD CONSTRAINT fault_diag_example_pkey PRIMARY KEY (run_id, example_key);


--
-- Name: fault_diag_run fault_diag_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_run
    ADD CONSTRAINT fault_diag_run_pkey PRIMARY KEY (run_id);


--
-- Name: fault_diag_scan_point fault_diag_scan_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_scan_point
    ADD CONSTRAINT fault_diag_scan_point_pkey PRIMARY KEY (run_id, system_id, ts);


--
-- Name: heatload_forecast_point heatload_forecast_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.heatload_forecast_point
    ADD CONSTRAINT heatload_forecast_point_pkey PRIMARY KEY (run_id, system_id, issued_at, horizon_min, valid_at);


--
-- Name: heatload_ledger heatload_ledger_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.heatload_ledger
    ADD CONSTRAINT heatload_ledger_pkey PRIMARY KEY (run_id, system_id, ts);


--
-- Name: heatload_run heatload_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.heatload_run
    ADD CONSTRAINT heatload_run_pkey PRIMARY KEY (run_id);


--
-- Name: hvac_cop_point hvac_cop_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.hvac_cop_point
    ADD CONSTRAINT hvac_cop_point_pkey PRIMARY KEY (run_id, hvac_id, ts);


--
-- Name: hvac_cop_run hvac_cop_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.hvac_cop_run
    ADD CONSTRAINT hvac_cop_run_pkey PRIMARY KEY (run_id);


--
-- Name: loss_daily loss_daily_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.loss_daily
    ADD CONSTRAINT loss_daily_pkey PRIMARY KEY (run_id, system_id, day);


--
-- Name: loss_ledger loss_ledger_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.loss_ledger
    ADD CONSTRAINT loss_ledger_pkey PRIMARY KEY (run_id, system_id, ts);


--
-- Name: loss_run loss_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.loss_run
    ADD CONSTRAINT loss_run_pkey PRIMARY KEY (run_id);


--
-- Name: model_run_curve model_run_curve_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.model_run_curve
    ADD CONSTRAINT model_run_curve_pkey PRIMARY KEY (run_id, iteration);


--
-- Name: model_run model_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.model_run
    ADD CONSTRAINT model_run_pkey PRIMARY KEY (run_id);


--
-- Name: mv_anomaly_run mv_anomaly_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.mv_anomaly_run
    ADD CONSTRAINT mv_anomaly_run_pkey PRIMARY KEY (run_id);


--
-- Name: mv_anomaly_score mv_anomaly_score_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.mv_anomaly_score
    ADD CONSTRAINT mv_anomaly_score_pkey PRIMARY KEY (run_id, system_id, ts);


--
-- Name: netload_forecast_peak netload_forecast_peak_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.netload_forecast_peak
    ADD CONSTRAINT netload_forecast_peak_pkey PRIMARY KEY (run_id, mp_id, origin_ts, target_date, model);


--
-- Name: netload_forecast_point netload_forecast_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.netload_forecast_point
    ADD CONSTRAINT netload_forecast_point_pkey PRIMARY KEY (run_id, mp_id, origin_ts, model, step);


--
-- Name: netload_forecast_run netload_forecast_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.netload_forecast_run
    ADD CONSTRAINT netload_forecast_run_pkey PRIMARY KEY (run_id);


--
-- Name: netload_forecast_score netload_forecast_score_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.netload_forecast_score
    ADD CONSTRAINT netload_forecast_score_pkey PRIMARY KEY (run_id, model);


--
-- Name: pcs_kpi pcs_kpi_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.pcs_kpi
    ADD CONSTRAINT pcs_kpi_pkey PRIMARY KEY (pcs_id, kpi_date, kpi_code);


--
-- Name: pcs_kpi_run pcs_kpi_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.pcs_kpi_run
    ADD CONSTRAINT pcs_kpi_run_pkey PRIMARY KEY (run_id);


--
-- Name: price_forecast_point price_forecast_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.price_forecast_point
    ADD CONSTRAINT price_forecast_point_pkey PRIMARY KEY (run_id, ems_id, origin_ts, model, horizon_h);


--
-- Name: price_forecast_run price_forecast_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.price_forecast_run
    ADD CONSTRAINT price_forecast_run_pkey PRIMARY KEY (run_id);


--
-- Name: price_forecast_score price_forecast_score_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.price_forecast_score
    ADD CONSTRAINT price_forecast_score_pkey PRIMARY KEY (run_id, model);


--
-- Name: rul_backtest rul_backtest_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.rul_backtest
    ADD CONSTRAINT rul_backtest_pkey PRIMARY KEY (run_id, system_id, snapshot_date, method);


--
-- Name: rul_forecast rul_forecast_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.rul_forecast
    ADD CONSTRAINT rul_forecast_pkey PRIMARY KEY (run_id, system_id, method);


--
-- Name: rul_run rul_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.rul_run
    ADD CONSTRAINT rul_run_pkey PRIMARY KEY (run_id);


--
-- Name: rul_score rul_score_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.rul_score
    ADD CONSTRAINT rul_score_pkey PRIMARY KEY (run_id, method, scope);


--
-- Name: soc_estimation_point soc_estimation_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_estimation_point
    ADD CONSTRAINT soc_estimation_point_pkey PRIMARY KEY (run_id, system_id, ts);


--
-- Name: soc_estimation_run soc_estimation_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_estimation_run
    ADD CONSTRAINT soc_estimation_run_pkey PRIMARY KEY (run_id);


--
-- Name: soc_estimation_score soc_estimation_score_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_estimation_score
    ADD CONSTRAINT soc_estimation_score_pkey PRIMARY KEY (run_id, method, scope);


--
-- Name: soc_estimation_state soc_estimation_state_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_estimation_state
    ADD CONSTRAINT soc_estimation_state_pkey PRIMARY KEY (run_id, system_id);


--
-- Name: soc_forecast_point soc_forecast_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_forecast_point
    ADD CONSTRAINT soc_forecast_point_pkey PRIMARY KEY (run_id, ems_id, origin_ts, method, step);


--
-- Name: soc_forecast_run soc_forecast_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_forecast_run
    ADD CONSTRAINT soc_forecast_run_pkey PRIMARY KEY (run_id);


--
-- Name: soc_forecast_score soc_forecast_score_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_forecast_score
    ADD CONSTRAINT soc_forecast_score_pkey PRIMARY KEY (run_id, method);


--
-- Name: thermal_forecast_point thermal_forecast_point_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.thermal_forecast_point
    ADD CONSTRAINT thermal_forecast_point_pkey PRIMARY KEY (run_id, target, system_id, origin_ts, horizon_min, method);


--
-- Name: thermal_forecast_run thermal_forecast_run_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.thermal_forecast_run
    ADD CONSTRAINT thermal_forecast_run_pkey PRIMARY KEY (run_id);


--
-- Name: thermal_forecast_score thermal_forecast_score_pkey; Type: CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.thermal_forecast_score
    ADD CONSTRAINT thermal_forecast_score_pkey PRIMARY KEY (run_id, target, horizon_min, method);


--
-- Name: batchlog batchlog_pkey; Type: CONSTRAINT; Schema: battery_raw; Owner: -
--

ALTER TABLE ONLY battery_raw.batchlog
    ADD CONSTRAINT batchlog_pkey PRIMARY KEY (batch_id);


--
-- Name: soc_estimation_data soc_estimation_data_pkey; Type: CONSTRAINT; Schema: battery_raw; Owner: -
--

ALTER TABLE ONLY battery_raw.soc_estimation_data
    ADD CONSTRAINT soc_estimation_data_pkey PRIMARY KEY (stg_id);


--
-- Name: soc_stg soc_stg_pkey; Type: CONSTRAINT; Schema: battery_raw; Owner: -
--

ALTER TABLE ONLY battery_raw.soc_stg
    ADD CONSTRAINT soc_stg_pkey PRIMARY KEY (stg_id);


--
-- Name: soc_estimation_data uq_soc_estimation_data_file_row; Type: CONSTRAINT; Schema: battery_raw; Owner: -
--

ALTER TABLE ONLY battery_raw.soc_estimation_data
    ADD CONSTRAINT uq_soc_estimation_data_file_row UNIQUE (source_file, row_no);


--
-- Name: soc_stg uq_soc_stg_file_row; Type: CONSTRAINT; Schema: battery_raw; Owner: -
--

ALTER TABLE ONLY battery_raw.soc_stg
    ADD CONSTRAINT uq_soc_stg_file_row UNIQUE (source_file, row_no);


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
-- Name: access_request access_request_pkey; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.access_request
    ADD CONSTRAINT access_request_pkey PRIMARY KEY (request_id);


--
-- Name: app_user app_user_email_key; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.app_user
    ADD CONSTRAINT app_user_email_key UNIQUE (email);


--
-- Name: app_user app_user_pkey; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.app_user
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (id);


--
-- Name: auth_audit auth_audit_pkey; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.auth_audit
    ADD CONSTRAINT auth_audit_pkey PRIMARY KEY (audit_id);


--
-- Name: privilege privilege_code_key; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.privilege
    ADD CONSTRAINT privilege_code_key UNIQUE (code);


--
-- Name: privilege privilege_pkey; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.privilege
    ADD CONSTRAINT privilege_pkey PRIMARY KEY (privilege_id);


--
-- Name: privilege privilege_resource_action_key; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.privilege
    ADD CONSTRAINT privilege_resource_action_key UNIQUE (resource, action);


--
-- Name: refresh_token refresh_token_pkey; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.refresh_token
    ADD CONSTRAINT refresh_token_pkey PRIMARY KEY (token_id);


--
-- Name: refresh_token refresh_token_token_hash_key; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.refresh_token
    ADD CONSTRAINT refresh_token_token_hash_key UNIQUE (token_hash);


--
-- Name: role role_pkey; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.role
    ADD CONSTRAINT role_pkey PRIMARY KEY (role_id);


--
-- Name: role_privilege role_privilege_pkey; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.role_privilege
    ADD CONSTRAINT role_privilege_pkey PRIMARY KEY (role_id, privilege_id);


--
-- Name: role role_role_code_key; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.role
    ADD CONSTRAINT role_role_code_key UNIQUE (role_code);


--
-- Name: role role_role_name_key; Type: CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.role
    ADD CONSTRAINT role_role_name_key UNIQUE (role_name);


--
-- Name: ix_activity_kind; Type: INDEX; Schema: battery_itops; Owner: -
--

CREATE INDEX ix_activity_kind ON battery_itops.activity_log USING btree (kind, ts DESC);


--
-- Name: ix_activity_request; Type: INDEX; Schema: battery_itops; Owner: -
--

CREATE INDEX ix_activity_request ON battery_itops.activity_log USING btree (request_id);


--
-- Name: ix_activity_ts; Type: INDEX; Schema: battery_itops; Owner: -
--

CREATE INDEX ix_activity_ts ON battery_itops.activity_log USING btree (ts DESC);


--
-- Name: ix_activity_user; Type: INDEX; Schema: battery_itops; Owner: -
--

CREATE INDEX ix_activity_user ON battery_itops.activity_log USING btree (user_email, ts DESC);


--
-- Name: as_price_delivery_start_idx; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX as_price_delivery_start_idx ON battery_master.as_price USING btree (delivery_start DESC);


--
-- Name: dam_price_delivery_start_idx; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX dam_price_delivery_start_idx ON battery_master.dam_price USING btree (delivery_start DESC);


--
-- Name: dispatch_outcome_interval_start_idx; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX dispatch_outcome_interval_start_idx ON battery_master.dispatch_outcome USING btree (interval_start DESC);


--
-- Name: dispatch_schedule_interval_start_idx; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX dispatch_schedule_interval_start_idx ON battery_master.dispatch_schedule USING btree (interval_start DESC);


--
-- Name: idx_asset_hierarchy_parent; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_asset_hierarchy_parent ON battery_master.asset_hierarchy USING btree (parent_asset_id);


--
-- Name: idx_battery_system_site; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_battery_system_site ON battery_master.battery_system USING btree (site_id);


--
-- Name: idx_container_system; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_container_system ON battery_master.battery_container USING btree (battery_system_id);


--
-- Name: idx_ems_controller_battery_system; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_ems_controller_battery_system ON battery_master.ems_controller USING btree (battery_system_id);


--
-- Name: idx_hvac_unit_battery_system; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_hvac_unit_battery_system ON battery_master.hvac_unit USING btree (battery_system_id);


--
-- Name: idx_module_pack; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_module_pack ON battery_master.battery_module USING btree (pack_id);


--
-- Name: idx_pack_container; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_pack_container ON battery_master.battery_pack USING btree (container_id);


--
-- Name: idx_tenant_contact_one_primary; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE UNIQUE INDEX idx_tenant_contact_one_primary ON battery_master.tenant_contact USING btree (tenant_id) WHERE is_primary;


--
-- Name: idx_tenant_contact_tenant; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_tenant_contact_tenant ON battery_master.tenant_contact USING btree (tenant_id);


--
-- Name: idx_tenant_email; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE UNIQUE INDEX idx_tenant_email ON battery_master.tenant USING btree (email) WHERE (email IS NOT NULL);


--
-- Name: idx_tenant_site_one_primary; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE UNIQUE INDEX idx_tenant_site_one_primary ON battery_master.tenant_site USING btree (site_id) WHERE is_primary_owner;


--
-- Name: idx_tenant_site_site; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_tenant_site_site ON battery_master.tenant_site USING btree (site_id);


--
-- Name: idx_tenant_site_tenant; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_tenant_site_tenant ON battery_master.tenant_site USING btree (tenant_id);


--
-- Name: idx_tenant_status; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX idx_tenant_status ON battery_master.tenant USING btree (status);


--
-- Name: ix_as_award_sys; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_as_award_sys ON battery_master.as_award USING btree (system_id, delivery_start);


--
-- Name: ix_episode_fault; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_episode_fault ON battery_master.fault_episode USING btree (fault_code);


--
-- Name: ix_episode_sys; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_episode_sys ON battery_master.fault_episode USING btree (system_id, detected_ts);


--
-- Name: ix_evt_sys; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_evt_sys ON battery_master.lifecycle_event USING btree (system_id, event_date);


--
-- Name: ix_fsig_fault; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_fsig_fault ON battery_master.fault_signature USING btree (fault_code);


--
-- Name: ix_grid_charge_site; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_grid_charge_site ON battery_master.grid_charge USING btree (site_id);


--
-- Name: ix_maint_episode; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_maint_episode ON battery_master.maintenance_action USING btree (episode_id);


--
-- Name: ix_optrun_sys; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_optrun_sys ON battery_master.optimization_run USING btree (system_id, horizon_start);


--
-- Name: ix_outcome_run; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_outcome_run ON battery_master.dispatch_outcome USING btree (run_id);


--
-- Name: ix_pred_actual; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_pred_actual ON battery_master.fault_prediction USING btree (actual_fault_code);


--
-- Name: ix_rpt_sys_date; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX ix_rpt_sys_date ON battery_master.capacity_test USING btree (system_id, test_date);


--
-- Name: price_forecast_target_ts_idx; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX price_forecast_target_ts_idx ON battery_master.price_forecast USING btree (target_ts DESC);


--
-- Name: price_scenario_target_ts_idx; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX price_scenario_target_ts_idx ON battery_master.price_scenario USING btree (target_ts DESC);


--
-- Name: rt_price_interval_start_idx; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE INDEX rt_price_interval_start_idx ON battery_master.rt_price USING btree (interval_start DESC);


--
-- Name: uq_fault_prediction_natural; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE UNIQUE INDEX uq_fault_prediction_natural ON battery_master.fault_prediction USING btree (model_version, system_id, asset_code, predicted_at);


--
-- Name: uq_fault_signature_code_signal; Type: INDEX; Schema: battery_master; Owner: -
--

CREATE UNIQUE INDEX uq_fault_signature_code_signal ON battery_master.fault_signature USING btree (fault_code, signal);


--
-- Name: heatload_forecast_point_valid_at_idx; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX heatload_forecast_point_valid_at_idx ON battery_ml.heatload_forecast_point USING btree (valid_at DESC);


--
-- Name: heatload_ledger_ts_idx; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX heatload_ledger_ts_idx ON battery_ml.heatload_ledger USING btree (ts DESC);


--
-- Name: hvac_cop_point_ts_idx; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX hvac_cop_point_ts_idx ON battery_ml.hvac_cop_point USING btree (ts DESC);


--
-- Name: idx_anomaly_run_system; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX idx_anomaly_run_system ON battery_ml.anomaly_run USING btree (battery_system_id, run_id DESC);


--
-- Name: idx_model_run_started; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX idx_model_run_started ON battery_ml.model_run USING btree (started_at DESC);


--
-- Name: idx_model_run_system; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX idx_model_run_system ON battery_ml.model_run USING btree (use_case, battery_system_id, run_id DESC);


--
-- Name: idx_model_run_use_case; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX idx_model_run_use_case ON battery_ml.model_run USING btree (use_case, run_id DESC);


--
-- Name: ix_bms_kpi_code_date; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_bms_kpi_code_date ON battery_ml.bms_kpi USING btree (kpi_code, kpi_date);


--
-- Name: ix_ems_kpi_code_date; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_ems_kpi_code_date ON battery_ml.ems_kpi USING btree (kpi_code, kpi_date);


--
-- Name: ix_fault_diag_candidate_run; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_fault_diag_candidate_run ON battery_ml.fault_diag_candidate USING btree (run_id, system_id, peak_ts);


--
-- Name: ix_fault_diag_example_ep; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_fault_diag_example_ep ON battery_ml.fault_diag_example USING btree (run_id, episode_id);


--
-- Name: ix_heatload_fc_run; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_heatload_fc_run ON battery_ml.heatload_forecast_point USING btree (run_id, system_id, horizon_min, valid_at);


--
-- Name: ix_heatload_ledger_run; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_heatload_ledger_run ON battery_ml.heatload_ledger USING btree (run_id, system_id, ts);


--
-- Name: ix_hvac_cop_point_run; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_hvac_cop_point_run ON battery_ml.hvac_cop_point USING btree (run_id, hvac_id, ts);


--
-- Name: ix_loss_ledger_run_system; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_loss_ledger_run_system ON battery_ml.loss_ledger USING btree (run_id, system_id, ts);


--
-- Name: ix_mv_anomaly_score_flag; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_mv_anomaly_score_flag ON battery_ml.mv_anomaly_score USING btree (run_id, ts) WHERE is_anomaly;


--
-- Name: ix_pcs_kpi_code_date; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX ix_pcs_kpi_code_date ON battery_ml.pcs_kpi USING btree (kpi_code, kpi_date);


--
-- Name: loss_ledger_ts_idx; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX loss_ledger_ts_idx ON battery_ml.loss_ledger USING btree (ts DESC);


--
-- Name: model_run_one_active; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX model_run_one_active ON battery_ml.model_run USING btree (use_case, COALESCE(battery_system_id, (0)::bigint)) WHERE is_active;


--
-- Name: mv_anomaly_score_ts_idx; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE INDEX mv_anomaly_score_ts_idx ON battery_ml.mv_anomaly_score USING btree (ts DESC);


--
-- Name: uq_aux_forecast_run_default; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX uq_aux_forecast_run_default ON battery_ml.aux_forecast_run USING btree (use_case) WHERE is_default;


--
-- Name: uq_efficiency_run_default; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX uq_efficiency_run_default ON battery_ml.efficiency_run USING btree (use_case) WHERE is_default;


--
-- Name: uq_netload_forecast_run_default; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX uq_netload_forecast_run_default ON battery_ml.netload_forecast_run USING btree (use_case) WHERE is_default;


--
-- Name: uq_price_forecast_run_default; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX uq_price_forecast_run_default ON battery_ml.price_forecast_run USING btree (use_case) WHERE is_default;


--
-- Name: uq_rul_run_default; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX uq_rul_run_default ON battery_ml.rul_run USING btree (use_case) WHERE is_default;


--
-- Name: uq_soc_estimation_run_default; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX uq_soc_estimation_run_default ON battery_ml.soc_estimation_run USING btree (use_case) WHERE is_default;


--
-- Name: uq_soc_forecast_run_default; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX uq_soc_forecast_run_default ON battery_ml.soc_forecast_run USING btree (use_case) WHERE is_default;


--
-- Name: uq_thermal_forecast_run_default; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX uq_thermal_forecast_run_default ON battery_ml.thermal_forecast_run USING btree (use_case) WHERE is_default;


--
-- Name: ux_mv_anomaly_default; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX ux_mv_anomaly_default ON battery_ml.mv_anomaly_run USING btree (system_id) WHERE (is_default AND (run_kind = 'train'::text));


--
-- Name: ux_mv_anomaly_live; Type: INDEX; Schema: battery_ml; Owner: -
--

CREATE UNIQUE INDEX ux_mv_anomaly_live ON battery_ml.mv_anomaly_run USING btree (parent_run_id) WHERE (run_kind = 'live'::text);


--
-- Name: idx_batchlog_file; Type: INDEX; Schema: battery_raw; Owner: -
--

CREATE INDEX idx_batchlog_file ON battery_raw.batchlog USING btree (file_name);


--
-- Name: idx_batchlog_problems; Type: INDEX; Schema: battery_raw; Owner: -
--

CREATE INDEX idx_batchlog_problems ON battery_raw.batchlog USING btree (started_at DESC) WHERE (status <> 'SUCCESS'::text);


--
-- Name: idx_batchlog_snapshot; Type: INDEX; Schema: battery_raw; Owner: -
--

CREATE INDEX idx_batchlog_snapshot ON battery_raw.batchlog USING btree (snapshot_time DESC);


--
-- Name: idx_batchlog_started; Type: INDEX; Schema: battery_raw; Owner: -
--

CREATE INDEX idx_batchlog_started ON battery_raw.batchlog USING btree (started_at DESC);


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
-- Name: ix_access_request_status; Type: INDEX; Schema: battery_users; Owner: -
--

CREATE INDEX ix_access_request_status ON battery_users.access_request USING btree (status, requested_at DESC);


--
-- Name: ix_auth_audit_ts; Type: INDEX; Schema: battery_users; Owner: -
--

CREATE INDEX ix_auth_audit_ts ON battery_users.auth_audit USING btree (ts DESC);


--
-- Name: ix_refresh_family; Type: INDEX; Schema: battery_users; Owner: -
--

CREATE INDEX ix_refresh_family ON battery_users.refresh_token USING btree (family_id);


--
-- Name: ix_refresh_user; Type: INDEX; Schema: battery_users; Owner: -
--

CREATE INDEX ix_refresh_user ON battery_users.refresh_token USING btree (user_id);


--
-- Name: ux_access_request_pending; Type: INDEX; Schema: battery_users; Owner: -
--

CREATE UNIQUE INDEX ux_access_request_pending ON battery_users.access_request USING btree (lower((email)::text)) WHERE (status = 'PENDING'::text);


--
-- Name: v_fault_training _RETURN; Type: RULE; Schema: battery_master; Owner: -
--

CREATE OR REPLACE VIEW battery_master.v_fault_training AS
 SELECT e.episode_id,
    e.system_id,
    s.system_name,
    e.asset_type,
    e.asset_code,
    e.fault_code,
    fc.subsystem,
    fc.category,
    fc.failure_mode,
    fc.is_safety_critical,
    e.onset_ts,
    e.detected_ts,
    e.resolved_ts,
    (EXTRACT(epoch FROM (e.detected_ts - e.onset_ts)) / 60.0) AS lead_time_min,
    (EXTRACT(epoch FROM (COALESCE(e.resolved_ts, now()) - e.detected_ts)) / 3600.0) AS duration_h,
    e.detection_method,
    e.severity_level,
    e.label_confidence,
    e.root_cause_confirmed,
    e.operating_context,
    e.downtime_min,
    e.energy_lost_kwh,
    e.is_ongoing,
    count(l.alarm_id) AS n_alarms,
    string_agg(DISTINCT l.alarm_id, ','::text ORDER BY l.alarm_id) AS alarm_ids,
    bool_or(ma.part_replaced) AS part_replaced,
    max(ma.cost_usd) AS repair_cost_usd,
    bool_or(ma.effective) AS repair_effective
   FROM ((((battery_master.fault_episode e
     JOIN battery_master.battery_system s ON ((s.battery_system_id = e.system_id)))
     JOIN battery_master.fault_catalog fc ON ((fc.fault_code = e.fault_code)))
     LEFT JOIN battery_master.fault_alarm_link l ON ((l.episode_id = e.episode_id)))
     LEFT JOIN battery_master.maintenance_action ma ON ((ma.episode_id = e.episode_id)))
  GROUP BY e.episode_id, s.system_name, fc.subsystem, fc.category, fc.failure_mode, fc.is_safety_critical;


--
-- Name: aging_snapshot aging_snapshot_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.aging_snapshot
    ADD CONSTRAINT aging_snapshot_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: alarm_catalog alarm_catalog_severity_level_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.alarm_catalog
    ADD CONSTRAINT alarm_catalog_severity_level_fkey FOREIGN KEY (severity_level) REFERENCES battery_master.alarm_severity(severity_level);


--
-- Name: as_award as_award_product_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.as_award
    ADD CONSTRAINT as_award_product_id_fkey FOREIGN KEY (product_id) REFERENCES battery_master.as_product(product_id) ON DELETE CASCADE;


--
-- Name: as_award as_award_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.as_award
    ADD CONSTRAINT as_award_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: as_price as_price_product_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.as_price
    ADD CONSTRAINT as_price_product_id_fkey FOREIGN KEY (product_id) REFERENCES battery_master.as_product(product_id) ON DELETE CASCADE;


--
-- Name: as_product as_product_market_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.as_product
    ADD CONSTRAINT as_product_market_id_fkey FOREIGN KEY (market_id) REFERENCES battery_master.market(market_id) ON DELETE CASCADE;


--
-- Name: asset_hierarchy asset_hierarchy_parent_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.asset_hierarchy
    ADD CONSTRAINT asset_hierarchy_parent_fkey FOREIGN KEY (parent_asset_id) REFERENCES battery_master.asset_hierarchy(asset_id) ON DELETE SET NULL;


--
-- Name: battery_container battery_container_battery_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_container
    ADD CONSTRAINT battery_container_battery_system_id_fkey FOREIGN KEY (battery_system_id) REFERENCES battery_master.battery_system(battery_system_id);


--
-- Name: battery_module battery_module_pack_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_module
    ADD CONSTRAINT battery_module_pack_id_fkey FOREIGN KEY (pack_id) REFERENCES battery_master.battery_pack(pack_id);


--
-- Name: battery_opt_param battery_opt_param_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_opt_param
    ADD CONSTRAINT battery_opt_param_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: battery_pack battery_pack_container_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_pack
    ADD CONSTRAINT battery_pack_container_id_fkey FOREIGN KEY (container_id) REFERENCES battery_master.battery_container(container_id);


--
-- Name: battery_provenance battery_provenance_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_provenance
    ADD CONSTRAINT battery_provenance_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: battery_system battery_system_chemistry_code_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_system
    ADD CONSTRAINT battery_system_chemistry_code_fkey FOREIGN KEY (chemistry_code) REFERENCES battery_master.battery_chemistry(chemistry_code);


--
-- Name: battery_system battery_system_site_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.battery_system
    ADD CONSTRAINT battery_system_site_id_fkey FOREIGN KEY (site_id) REFERENCES battery_master.site(site_id);


--
-- Name: capacity_test capacity_test_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.capacity_test
    ADD CONSTRAINT capacity_test_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: current_sensor_cal current_sensor_cal_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.current_sensor_cal
    ADD CONSTRAINT current_sensor_cal_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: dam_price dam_price_node_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.dam_price
    ADD CONSTRAINT dam_price_node_id_fkey FOREIGN KEY (node_id) REFERENCES battery_master.price_node(node_id) ON DELETE CASCADE;


--
-- Name: decision_state decision_state_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.decision_state
    ADD CONSTRAINT decision_state_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_master.optimization_run(run_id) ON DELETE CASCADE;


--
-- Name: degradation_cost_curve degradation_cost_curve_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.degradation_cost_curve
    ADD CONSTRAINT degradation_cost_curve_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: demand_tariff demand_tariff_site_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.demand_tariff
    ADD CONSTRAINT demand_tariff_site_id_fkey FOREIGN KEY (site_id) REFERENCES battery_master.site(site_id) ON DELETE CASCADE;


--
-- Name: dispatch_outcome dispatch_outcome_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.dispatch_outcome
    ADD CONSTRAINT dispatch_outcome_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_master.optimization_run(run_id) ON DELETE SET NULL;


--
-- Name: dispatch_outcome dispatch_outcome_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.dispatch_outcome
    ADD CONSTRAINT dispatch_outcome_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: dispatch_schedule dispatch_schedule_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.dispatch_schedule
    ADD CONSTRAINT dispatch_schedule_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_master.optimization_run(run_id) ON DELETE CASCADE;


--
-- Name: efficiency_curve efficiency_curve_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.efficiency_curve
    ADD CONSTRAINT efficiency_curve_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: ems_controller ems_controller_battery_system_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.ems_controller
    ADD CONSTRAINT ems_controller_battery_system_fkey FOREIGN KEY (battery_system_id) REFERENCES battery_master.battery_system(battery_system_id);


--
-- Name: ems_tariff_period ems_tariff_period_ems_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.ems_tariff_period
    ADD CONSTRAINT ems_tariff_period_ems_id_fkey FOREIGN KEY (ems_id) REFERENCES battery_master.ems_controller(ems_id) ON DELETE CASCADE;


--
-- Name: fault_alarm_link fault_alarm_link_episode_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_alarm_link
    ADD CONSTRAINT fault_alarm_link_episode_id_fkey FOREIGN KEY (episode_id) REFERENCES battery_master.fault_episode(episode_id) ON DELETE CASCADE;


--
-- Name: fault_catalog fault_catalog_default_severity_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_catalog
    ADD CONSTRAINT fault_catalog_default_severity_fkey FOREIGN KEY (default_severity) REFERENCES battery_master.alarm_severity(severity_level);


--
-- Name: fault_episode fault_episode_fault_code_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_episode
    ADD CONSTRAINT fault_episode_fault_code_fkey FOREIGN KEY (fault_code) REFERENCES battery_master.fault_catalog(fault_code);


--
-- Name: fault_episode fault_episode_severity_level_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_episode
    ADD CONSTRAINT fault_episode_severity_level_fkey FOREIGN KEY (severity_level) REFERENCES battery_master.alarm_severity(severity_level);


--
-- Name: fault_episode fault_episode_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_episode
    ADD CONSTRAINT fault_episode_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: fault_prediction fault_prediction_actual_fault_code_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_prediction
    ADD CONSTRAINT fault_prediction_actual_fault_code_fkey FOREIGN KEY (actual_fault_code) REFERENCES battery_master.fault_catalog(fault_code);


--
-- Name: fault_prediction fault_prediction_episode_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_prediction
    ADD CONSTRAINT fault_prediction_episode_id_fkey FOREIGN KEY (episode_id) REFERENCES battery_master.fault_episode(episode_id) ON DELETE SET NULL;


--
-- Name: fault_prediction fault_prediction_predicted_fault_code_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_prediction
    ADD CONSTRAINT fault_prediction_predicted_fault_code_fkey FOREIGN KEY (predicted_fault_code) REFERENCES battery_master.fault_catalog(fault_code);


--
-- Name: fault_prediction fault_prediction_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_prediction
    ADD CONSTRAINT fault_prediction_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: fault_signature fault_signature_fault_code_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.fault_signature
    ADD CONSTRAINT fault_signature_fault_code_fkey FOREIGN KEY (fault_code) REFERENCES battery_master.fault_catalog(fault_code) ON DELETE CASCADE;


--
-- Name: generation_asset generation_asset_site_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.generation_asset
    ADD CONSTRAINT generation_asset_site_id_fkey FOREIGN KEY (site_id) REFERENCES battery_master.site(site_id) ON DELETE CASCADE;


--
-- Name: grid_charge grid_charge_site_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.grid_charge
    ADD CONSTRAINT grid_charge_site_id_fkey FOREIGN KEY (site_id) REFERENCES battery_master.site(site_id) ON DELETE CASCADE;


--
-- Name: hvac_unit hvac_unit_battery_system_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.hvac_unit
    ADD CONSTRAINT hvac_unit_battery_system_fkey FOREIGN KEY (battery_system_id) REFERENCES battery_master.battery_system(battery_system_id);


--
-- Name: interconnection_limit interconnection_limit_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.interconnection_limit
    ADD CONSTRAINT interconnection_limit_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: lifecycle_event lifecycle_event_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.lifecycle_event
    ADD CONSTRAINT lifecycle_event_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: maintenance_action maintenance_action_episode_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.maintenance_action
    ADD CONSTRAINT maintenance_action_episode_id_fkey FOREIGN KEY (episode_id) REFERENCES battery_master.fault_episode(episode_id) ON DELETE SET NULL;


--
-- Name: maintenance_action maintenance_action_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.maintenance_action
    ADD CONSTRAINT maintenance_action_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: metering_point metering_point_site_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.metering_point
    ADD CONSTRAINT metering_point_site_id_fkey FOREIGN KEY (site_id) REFERENCES battery_master.site(site_id) ON DELETE CASCADE;


--
-- Name: optimization_run optimization_run_study_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.optimization_run
    ADD CONSTRAINT optimization_run_study_id_fkey FOREIGN KEY (study_id) REFERENCES battery_ml.arb_study(study_id) ON DELETE CASCADE;


--
-- Name: optimization_run optimization_run_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.optimization_run
    ADD CONSTRAINT optimization_run_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: pcs_alarm_type pcs_alarm_type_default_severity_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs_alarm_type
    ADD CONSTRAINT pcs_alarm_type_default_severity_fkey FOREIGN KEY (default_severity) REFERENCES battery_master.alarm_severity(severity_level);


--
-- Name: pcs pcs_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.pcs
    ADD CONSTRAINT pcs_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: price_forecast price_forecast_node_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.price_forecast
    ADD CONSTRAINT price_forecast_node_id_fkey FOREIGN KEY (node_id) REFERENCES battery_master.price_node(node_id) ON DELETE CASCADE;


--
-- Name: price_node price_node_market_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.price_node
    ADD CONSTRAINT price_node_market_id_fkey FOREIGN KEY (market_id) REFERENCES battery_master.market(market_id) ON DELETE CASCADE;


--
-- Name: price_node price_node_site_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.price_node
    ADD CONSTRAINT price_node_site_id_fkey FOREIGN KEY (site_id) REFERENCES battery_master.site(site_id);


--
-- Name: price_scenario price_scenario_node_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.price_scenario
    ADD CONSTRAINT price_scenario_node_id_fkey FOREIGN KEY (node_id) REFERENCES battery_master.price_node(node_id) ON DELETE CASCADE;


--
-- Name: rt_price rt_price_node_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.rt_price
    ADD CONSTRAINT rt_price_node_id_fkey FOREIGN KEY (node_id) REFERENCES battery_master.price_node(node_id) ON DELETE CASCADE;


--
-- Name: soc_reference soc_reference_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.soc_reference
    ADD CONSTRAINT soc_reference_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: tenant_contact tenant_contact_tenant_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.tenant_contact
    ADD CONSTRAINT tenant_contact_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES battery_master.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: tenant_site tenant_site_site_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.tenant_site
    ADD CONSTRAINT tenant_site_site_id_fkey FOREIGN KEY (site_id) REFERENCES battery_master.site(site_id) ON DELETE CASCADE;


--
-- Name: tenant_site tenant_site_tenant_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.tenant_site
    ADD CONSTRAINT tenant_site_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES battery_master.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: transformer transformer_site_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.transformer
    ADD CONSTRAINT transformer_site_id_fkey FOREIGN KEY (site_id) REFERENCES battery_master.site(site_id);


--
-- Name: weather_station weather_station_site_id_fkey; Type: FK CONSTRAINT; Schema: battery_master; Owner: -
--

ALTER TABLE ONLY battery_master.weather_station
    ADD CONSTRAINT weather_station_site_id_fkey FOREIGN KEY (site_id) REFERENCES battery_master.site(site_id) ON DELETE CASCADE;


--
-- Name: anomaly_module_result anomaly_module_result_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.anomaly_module_result
    ADD CONSTRAINT anomaly_module_result_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.anomaly_run(run_id) ON DELETE CASCADE;


--
-- Name: anomaly_point anomaly_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.anomaly_point
    ADD CONSTRAINT anomaly_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.anomaly_run(run_id) ON DELETE CASCADE;


--
-- Name: anomaly_run anomaly_run_battery_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.anomaly_run
    ADD CONSTRAINT anomaly_run_battery_system_id_fkey FOREIGN KEY (battery_system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: anomaly_run anomaly_run_parent_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.anomaly_run
    ADD CONSTRAINT anomaly_run_parent_run_id_fkey FOREIGN KEY (parent_run_id) REFERENCES battery_ml.anomaly_run(run_id) ON DELETE SET NULL;


--
-- Name: arb_backtest arb_backtest_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.arb_backtest
    ADD CONSTRAINT arb_backtest_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_master.optimization_run(run_id) ON DELETE SET NULL;


--
-- Name: arb_backtest arb_backtest_study_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.arb_backtest
    ADD CONSTRAINT arb_backtest_study_id_fkey FOREIGN KEY (study_id) REFERENCES battery_ml.arb_study(study_id) ON DELETE CASCADE;


--
-- Name: arb_study_day arb_study_day_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.arb_study_day
    ADD CONSTRAINT arb_study_day_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_master.optimization_run(run_id) ON DELETE SET NULL;


--
-- Name: arb_study_day arb_study_day_study_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.arb_study_day
    ADD CONSTRAINT arb_study_day_study_id_fkey FOREIGN KEY (study_id) REFERENCES battery_ml.arb_study(study_id) ON DELETE CASCADE;


--
-- Name: arb_study arb_study_node_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.arb_study
    ADD CONSTRAINT arb_study_node_id_fkey FOREIGN KEY (node_id) REFERENCES battery_master.price_node(node_id) ON DELETE CASCADE;


--
-- Name: arb_study arb_study_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.arb_study
    ADD CONSTRAINT arb_study_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: aux_forecast_daily aux_forecast_daily_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.aux_forecast_daily
    ADD CONSTRAINT aux_forecast_daily_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.aux_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: aux_forecast_point aux_forecast_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.aux_forecast_point
    ADD CONSTRAINT aux_forecast_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.aux_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: aux_forecast_score aux_forecast_score_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.aux_forecast_score
    ADD CONSTRAINT aux_forecast_score_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.aux_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: bms_kpi bms_kpi_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.bms_kpi
    ADD CONSTRAINT bms_kpi_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.bms_kpi_run(run_id) ON DELETE SET NULL;


--
-- Name: bms_kpi bms_kpi_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.bms_kpi
    ADD CONSTRAINT bms_kpi_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: efficiency_cycle efficiency_cycle_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.efficiency_cycle
    ADD CONSTRAINT efficiency_cycle_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.efficiency_run(run_id) ON DELETE CASCADE;


--
-- Name: efficiency_score efficiency_score_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.efficiency_score
    ADD CONSTRAINT efficiency_score_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.efficiency_run(run_id) ON DELETE CASCADE;


--
-- Name: ems_kpi ems_kpi_ems_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.ems_kpi
    ADD CONSTRAINT ems_kpi_ems_id_fkey FOREIGN KEY (ems_id) REFERENCES battery_master.ems_controller(ems_id) ON DELETE CASCADE;


--
-- Name: ems_kpi ems_kpi_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.ems_kpi
    ADD CONSTRAINT ems_kpi_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.ems_kpi_run(run_id) ON DELETE SET NULL;


--
-- Name: fault_diag_candidate fault_diag_candidate_actual_fault_code_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_candidate
    ADD CONSTRAINT fault_diag_candidate_actual_fault_code_fkey FOREIGN KEY (actual_fault_code) REFERENCES battery_master.fault_catalog(fault_code);


--
-- Name: fault_diag_candidate fault_diag_candidate_episode_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_candidate
    ADD CONSTRAINT fault_diag_candidate_episode_id_fkey FOREIGN KEY (episode_id) REFERENCES battery_master.fault_episode(episode_id) ON DELETE SET NULL;


--
-- Name: fault_diag_candidate fault_diag_candidate_fault_code_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_candidate
    ADD CONSTRAINT fault_diag_candidate_fault_code_fkey FOREIGN KEY (fault_code) REFERENCES battery_master.fault_catalog(fault_code);


--
-- Name: fault_diag_candidate fault_diag_candidate_prediction_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_candidate
    ADD CONSTRAINT fault_diag_candidate_prediction_id_fkey FOREIGN KEY (prediction_id) REFERENCES battery_master.fault_prediction(prediction_id) ON DELETE SET NULL;


--
-- Name: fault_diag_candidate fault_diag_candidate_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_candidate
    ADD CONSTRAINT fault_diag_candidate_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.fault_diag_run(run_id) ON DELETE CASCADE;


--
-- Name: fault_diag_example fault_diag_example_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_example
    ADD CONSTRAINT fault_diag_example_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.fault_diag_run(run_id) ON DELETE CASCADE;


--
-- Name: fault_diag_scan_point fault_diag_scan_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.fault_diag_scan_point
    ADD CONSTRAINT fault_diag_scan_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.fault_diag_run(run_id) ON DELETE CASCADE;


--
-- Name: heatload_forecast_point heatload_forecast_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.heatload_forecast_point
    ADD CONSTRAINT heatload_forecast_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.heatload_run(run_id) ON DELETE CASCADE;


--
-- Name: heatload_ledger heatload_ledger_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.heatload_ledger
    ADD CONSTRAINT heatload_ledger_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.heatload_run(run_id) ON DELETE CASCADE;


--
-- Name: hvac_cop_point hvac_cop_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.hvac_cop_point
    ADD CONSTRAINT hvac_cop_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.hvac_cop_run(run_id) ON DELETE CASCADE;


--
-- Name: loss_daily loss_daily_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.loss_daily
    ADD CONSTRAINT loss_daily_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.loss_run(run_id) ON DELETE CASCADE;


--
-- Name: loss_ledger loss_ledger_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.loss_ledger
    ADD CONSTRAINT loss_ledger_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.loss_run(run_id) ON DELETE CASCADE;


--
-- Name: model_run_curve model_run_curve_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.model_run_curve
    ADD CONSTRAINT model_run_curve_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.model_run(run_id) ON DELETE CASCADE;


--
-- Name: model_run model_run_parent_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.model_run
    ADD CONSTRAINT model_run_parent_run_id_fkey FOREIGN KEY (parent_run_id) REFERENCES battery_ml.model_run(run_id) ON DELETE SET NULL;


--
-- Name: mv_anomaly_run mv_anomaly_run_parent_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.mv_anomaly_run
    ADD CONSTRAINT mv_anomaly_run_parent_run_id_fkey FOREIGN KEY (parent_run_id) REFERENCES battery_ml.mv_anomaly_run(run_id) ON DELETE CASCADE;


--
-- Name: mv_anomaly_run mv_anomaly_run_system_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.mv_anomaly_run
    ADD CONSTRAINT mv_anomaly_run_system_id_fkey FOREIGN KEY (system_id) REFERENCES battery_master.battery_system(battery_system_id) ON DELETE CASCADE;


--
-- Name: mv_anomaly_score mv_anomaly_score_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.mv_anomaly_score
    ADD CONSTRAINT mv_anomaly_score_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.mv_anomaly_run(run_id) ON DELETE CASCADE;


--
-- Name: netload_forecast_peak netload_forecast_peak_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.netload_forecast_peak
    ADD CONSTRAINT netload_forecast_peak_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.netload_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: netload_forecast_point netload_forecast_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.netload_forecast_point
    ADD CONSTRAINT netload_forecast_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.netload_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: netload_forecast_score netload_forecast_score_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.netload_forecast_score
    ADD CONSTRAINT netload_forecast_score_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.netload_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: pcs_kpi pcs_kpi_pcs_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.pcs_kpi
    ADD CONSTRAINT pcs_kpi_pcs_id_fkey FOREIGN KEY (pcs_id) REFERENCES battery_master.pcs(pcs_id) ON DELETE CASCADE;


--
-- Name: pcs_kpi pcs_kpi_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.pcs_kpi
    ADD CONSTRAINT pcs_kpi_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.pcs_kpi_run(run_id) ON DELETE SET NULL;


--
-- Name: price_forecast_point price_forecast_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.price_forecast_point
    ADD CONSTRAINT price_forecast_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.price_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: price_forecast_score price_forecast_score_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.price_forecast_score
    ADD CONSTRAINT price_forecast_score_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.price_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: rul_backtest rul_backtest_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.rul_backtest
    ADD CONSTRAINT rul_backtest_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.rul_run(run_id) ON DELETE CASCADE;


--
-- Name: rul_forecast rul_forecast_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.rul_forecast
    ADD CONSTRAINT rul_forecast_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.rul_run(run_id) ON DELETE CASCADE;


--
-- Name: rul_score rul_score_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.rul_score
    ADD CONSTRAINT rul_score_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.rul_run(run_id) ON DELETE CASCADE;


--
-- Name: soc_estimation_point soc_estimation_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_estimation_point
    ADD CONSTRAINT soc_estimation_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.soc_estimation_run(run_id) ON DELETE CASCADE;


--
-- Name: soc_estimation_score soc_estimation_score_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_estimation_score
    ADD CONSTRAINT soc_estimation_score_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.soc_estimation_run(run_id) ON DELETE CASCADE;


--
-- Name: soc_estimation_state soc_estimation_state_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_estimation_state
    ADD CONSTRAINT soc_estimation_state_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.soc_estimation_run(run_id) ON DELETE CASCADE;


--
-- Name: soc_forecast_point soc_forecast_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_forecast_point
    ADD CONSTRAINT soc_forecast_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.soc_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: soc_forecast_score soc_forecast_score_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.soc_forecast_score
    ADD CONSTRAINT soc_forecast_score_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.soc_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: thermal_forecast_point thermal_forecast_point_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.thermal_forecast_point
    ADD CONSTRAINT thermal_forecast_point_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.thermal_forecast_run(run_id) ON DELETE CASCADE;


--
-- Name: thermal_forecast_score thermal_forecast_score_run_id_fkey; Type: FK CONSTRAINT; Schema: battery_ml; Owner: -
--

ALTER TABLE ONLY battery_ml.thermal_forecast_score
    ADD CONSTRAINT thermal_forecast_score_run_id_fkey FOREIGN KEY (run_id) REFERENCES battery_ml.thermal_forecast_run(run_id) ON DELETE CASCADE;


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
-- Name: access_request access_request_role_id_fkey; Type: FK CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.access_request
    ADD CONSTRAINT access_request_role_id_fkey FOREIGN KEY (role_id) REFERENCES battery_users.role(role_id);


--
-- Name: access_request access_request_tenant_id_fkey; Type: FK CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.access_request
    ADD CONSTRAINT access_request_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES battery_master.tenant(tenant_id) ON DELETE SET NULL;


--
-- Name: access_request access_request_user_id_fkey; Type: FK CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.access_request
    ADD CONSTRAINT access_request_user_id_fkey FOREIGN KEY (user_id) REFERENCES battery_users.app_user(id) ON DELETE SET NULL;


--
-- Name: app_user app_user_role_id_fkey; Type: FK CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.app_user
    ADD CONSTRAINT app_user_role_id_fkey FOREIGN KEY (role_id) REFERENCES battery_users.role(role_id);


--
-- Name: app_user app_user_tenant_id_fkey; Type: FK CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.app_user
    ADD CONSTRAINT app_user_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES battery_master.tenant(tenant_id) ON DELETE SET NULL;


--
-- Name: refresh_token refresh_token_user_id_fkey; Type: FK CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.refresh_token
    ADD CONSTRAINT refresh_token_user_id_fkey FOREIGN KEY (user_id) REFERENCES battery_users.app_user(id) ON DELETE CASCADE;


--
-- Name: role_privilege role_privilege_privilege_id_fkey; Type: FK CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.role_privilege
    ADD CONSTRAINT role_privilege_privilege_id_fkey FOREIGN KEY (privilege_id) REFERENCES battery_users.privilege(privilege_id) ON DELETE CASCADE;


--
-- Name: role_privilege role_privilege_role_id_fkey; Type: FK CONSTRAINT; Schema: battery_users; Owner: -
--

ALTER TABLE ONLY battery_users.role_privilege
    ADD CONSTRAINT role_privilege_role_id_fkey FOREIGN KEY (role_id) REFERENCES battery_users.role(role_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict V4Qqx9kMLZtwhCWEP9rKpwXFfWtGnxR0zFmG6gOJFw35ucW5nRsqwL0Ag1KLXOR



-- ============================================================ TimescaleDB hypertables
SET search_path = public;
SELECT create_hypertable('"battery_master"."as_price"', by_range('delivery_start', INTERVAL '30 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."dam_price"', by_range('delivery_start', INTERVAL '30 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."dispatch_outcome"', by_range('interval_start', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."dispatch_schedule"', by_range('interval_start', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."price_forecast"', by_range('target_ts', INTERVAL '30 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."price_scenario"', by_range('target_ts', INTERVAL '30 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."rt_price"', by_range('interval_start', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_ml"."heatload_forecast_point"', by_range('valid_at', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_ml"."heatload_ledger"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_ml"."hvac_cop_point"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_ml"."loss_ledger"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_ml"."mv_anomaly_score"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
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
SET search_path = "battery_master", public;
CREATE MATERIALIZED VIEW "battery_master"."dispatch_pnl_daily"
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT system_id,
    public.time_bucket('1 day'::interval, interval_start) AS bucket_day,
    sum(
        CASE
            WHEN (energy_mwh > (0)::numeric) THEN energy_mwh
            ELSE (0)::numeric
        END) AS discharge_mwh,
    sum(
        CASE
            WHEN (energy_mwh < (0)::numeric) THEN (- energy_mwh)
            ELSE (0)::numeric
        END) AS charge_mwh,
    sum(gross_revenue_usd) AS gross_revenue_usd,
    sum(degradation_cost_usd) AS degradation_cost_usd,
    sum(grid_cost_usd) AS grid_cost_usd,
    sum(net_pnl_usd) AS net_pnl_usd
   FROM battery_master.dispatch_outcome
  GROUP BY system_id, (public.time_bucket('1 day'::interval, interval_start))
WITH NO DATA;

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
ALTER TABLE "battery_master"."as_price" SET (timescaledb.compress, timescaledb.compress_segmentby = '"product_id"', timescaledb.compress_orderby = '"delivery_start" DESC NULLS FIRST');
ALTER TABLE "battery_master"."dam_price" SET (timescaledb.compress, timescaledb.compress_segmentby = '"node_id"', timescaledb.compress_orderby = '"delivery_start" DESC NULLS FIRST');
ALTER TABLE "battery_master"."dispatch_outcome" SET (timescaledb.compress, timescaledb.compress_segmentby = '"system_id"', timescaledb.compress_orderby = '"interval_start" DESC NULLS FIRST');
ALTER TABLE "battery_master"."dispatch_schedule" SET (timescaledb.compress, timescaledb.compress_segmentby = '"run_id"', timescaledb.compress_orderby = '"interval_start" DESC NULLS FIRST');
ALTER TABLE "battery_master"."price_forecast" SET (timescaledb.compress, timescaledb.compress_segmentby = '"node_id"', timescaledb.compress_orderby = '"target_ts" DESC NULLS FIRST, "issued_at" DESC NULLS FIRST');
ALTER TABLE "battery_master"."price_scenario" SET (timescaledb.compress, timescaledb.compress_segmentby = '"node_id"', timescaledb.compress_orderby = '"target_ts" DESC NULLS FIRST');
ALTER TABLE "battery_master"."rt_price" SET (timescaledb.compress, timescaledb.compress_segmentby = '"node_id"', timescaledb.compress_orderby = '"interval_start" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."demand_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"metering_point_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."ems_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"ems_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."hvac_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"hvac_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."module_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"module_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."pcs_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"pcs_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."system_telemetry" SET (timescaledb.compress, timescaledb.compress_segmentby = '"system_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
ALTER TABLE "battery_telemetry"."weather_actual" SET (timescaledb.compress, timescaledb.compress_segmentby = '"station_id"', timescaledb.compress_orderby = '"ts" DESC NULLS FIRST');
SELECT add_compression_policy('"battery_master"."as_price"', compress_after => INTERVAL '90 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."dam_price"', compress_after => INTERVAL '90 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."dispatch_outcome"', compress_after => INTERVAL '90 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."dispatch_schedule"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."price_forecast"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."price_scenario"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."rt_price"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."demand_telemetry"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."ems_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."hvac_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."module_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."pcs_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."system_telemetry"', compress_after => INTERVAL '7 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_telemetry"."weather_actual"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_master"."dispatch_pnl_daily"', start_offset => INTERVAL '7 days', end_offset => INTERVAL '01:00:00', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
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
SELECT add_retention_policy('"battery_master"."price_forecast"', drop_after => INTERVAL '400 days', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_master"."price_scenario"', drop_after => INTERVAL '180 days', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."demand_telemetry"', drop_after => INTERVAL '3 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."ems_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."hvac_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."module_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."pcs_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_telemetry"."system_telemetry"', drop_after => INTERVAL '2 years', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);

-- ============================================================ database settings
-- the APIs rely on the default search_path; applied to whichever database runs this script
DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET search_path = battery_master, battery_telemetry, battery_raw, public', current_database());
END $$;

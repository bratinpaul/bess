-- BESS database DDL: battery_master
-- Generated 2026-10-23 by db_docs/generate_ddl.py from database Battery
-- Sections: extensions, pg_dump schema DDL, TimescaleDB hypertables + compression, continuous aggregates,
--           views on continuous aggregates, TimescaleDB policies

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================ schema DDL (pg_dump)
--
-- PostgreSQL database dump
--

\restrict CwpZR7eReEKlqaNgL6fZYcyly8tLM8cbpbhsvP0pB2dej4ygwRKZjkbcoH23wn3

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
-- Name: battery_master; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_master;


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
-- PostgreSQL database dump complete
--

\unrestrict CwpZR7eReEKlqaNgL6fZYcyly8tLM8cbpbhsvP0pB2dej4ygwRKZjkbcoH23wn3



-- ============================================================ TimescaleDB hypertables
SET search_path = public;
SELECT create_hypertable('"battery_master"."as_price"', by_range('delivery_start', INTERVAL '30 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."dam_price"', by_range('delivery_start', INTERVAL '30 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."dispatch_outcome"', by_range('interval_start', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."dispatch_schedule"', by_range('interval_start', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."price_forecast"', by_range('target_ts', INTERVAL '30 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."price_scenario"', by_range('target_ts', INTERVAL '30 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_master"."rt_price"', by_range('interval_start', INTERVAL '7 days'), if_not_exists => TRUE);

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

SET search_path = public;

-- ============================================================ compression settings and policies
ALTER TABLE "battery_master"."as_price" SET (timescaledb.compress, timescaledb.compress_segmentby = '"product_id"', timescaledb.compress_orderby = '"delivery_start" DESC NULLS FIRST');
ALTER TABLE "battery_master"."dam_price" SET (timescaledb.compress, timescaledb.compress_segmentby = '"node_id"', timescaledb.compress_orderby = '"delivery_start" DESC NULLS FIRST');
ALTER TABLE "battery_master"."dispatch_outcome" SET (timescaledb.compress, timescaledb.compress_segmentby = '"system_id"', timescaledb.compress_orderby = '"interval_start" DESC NULLS FIRST');
ALTER TABLE "battery_master"."dispatch_schedule" SET (timescaledb.compress, timescaledb.compress_segmentby = '"run_id"', timescaledb.compress_orderby = '"interval_start" DESC NULLS FIRST');
ALTER TABLE "battery_master"."price_forecast" SET (timescaledb.compress, timescaledb.compress_segmentby = '"node_id"', timescaledb.compress_orderby = '"target_ts" DESC NULLS FIRST, "issued_at" DESC NULLS FIRST');
ALTER TABLE "battery_master"."price_scenario" SET (timescaledb.compress, timescaledb.compress_segmentby = '"node_id"', timescaledb.compress_orderby = '"target_ts" DESC NULLS FIRST');
ALTER TABLE "battery_master"."rt_price" SET (timescaledb.compress, timescaledb.compress_segmentby = '"node_id"', timescaledb.compress_orderby = '"interval_start" DESC NULLS FIRST');
SELECT add_compression_policy('"battery_master"."as_price"', compress_after => INTERVAL '90 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."dam_price"', compress_after => INTERVAL '90 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."dispatch_outcome"', compress_after => INTERVAL '90 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."dispatch_schedule"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."price_forecast"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."price_scenario"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_compression_policy('"battery_master"."rt_price"', compress_after => INTERVAL '30 days', schedule_interval => INTERVAL '12 hours', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('"battery_master"."dispatch_pnl_daily"', start_offset => INTERVAL '7 days', end_offset => INTERVAL '01:00:00', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_master"."price_forecast"', drop_after => INTERVAL '400 days', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('"battery_master"."price_scenario"', drop_after => INTERVAL '180 days', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);

-- BESS database DDL: battery_raw
-- Generated 2026-10-22 by db_docs/generate_ddl.py from database Battery
-- Sections: extensions, pg_dump schema DDL, TimescaleDB hypertables + compression, continuous aggregates,
--           views on continuous aggregates, TimescaleDB policies

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================ schema DDL (pg_dump)
--
-- PostgreSQL database dump
--

\restrict XoOVqemcMlS9ARVOJgob8So9WdJy4eMsozJV8owEXhMoFYZYzgJeBdrUbM8ojhf

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
-- Name: battery_raw; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_raw;


SET default_tablespace = '';

SET default_table_access_method = heap;

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
-- PostgreSQL database dump complete
--

\unrestrict XoOVqemcMlS9ARVOJgob8So9WdJy4eMsozJV8owEXhMoFYZYzgJeBdrUbM8ojhf



-- ============================================================ TimescaleDB hypertables
SET search_path = public;

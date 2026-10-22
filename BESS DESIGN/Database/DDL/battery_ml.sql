-- BESS database DDL: battery_ml
-- Generated 2026-10-22 by db_docs/generate_ddl.py from database Battery
-- Sections: extensions, pg_dump schema DDL, TimescaleDB hypertables + compression, continuous aggregates,
--           views on continuous aggregates, TimescaleDB policies

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================ schema DDL (pg_dump)
--
-- PostgreSQL database dump
--

\restrict 3MyWi2WRgnbPRQq3Fdzdr3DroBJLwbbEj6HMjRA8f7Jw8AxNsd7cDVrK3JmXIju

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
-- Name: battery_ml; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_ml;


SET default_tablespace = '';

SET default_table_access_method = heap;

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
-- PostgreSQL database dump complete
--

\unrestrict 3MyWi2WRgnbPRQq3Fdzdr3DroBJLwbbEj6HMjRA8f7Jw8AxNsd7cDVrK3JmXIju



-- ============================================================ TimescaleDB hypertables
SET search_path = public;
SELECT create_hypertable('"battery_ml"."heatload_forecast_point"', by_range('valid_at', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_ml"."heatload_ledger"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_ml"."hvac_cop_point"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_ml"."loss_ledger"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
SELECT create_hypertable('"battery_ml"."mv_anomaly_score"', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);

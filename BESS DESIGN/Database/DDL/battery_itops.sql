-- BESS database DDL: battery_itops
-- Generated 2026-10-23 by db_docs/generate_ddl.py from database Battery
-- Sections: extensions, pg_dump schema DDL, TimescaleDB hypertables + compression, continuous aggregates,
--           views on continuous aggregates, TimescaleDB policies

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================ schema DDL (pg_dump)
--
-- PostgreSQL database dump
--

\restrict CjhQsQkvblu09cieKcDDanZLVnyCemiJK77hdy37aTifaRLKc5rIiTbPpbb0SCG

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


SET default_tablespace = '';

SET default_table_access_method = heap;

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
    error_code text,
    CONSTRAINT activity_log_kind_check CHECK ((kind = ANY (ARRAY['REQUEST'::text, 'AUTH'::text, 'LOAD'::text, 'KPI'::text, 'TRAINING'::text, 'ERROR'::text]))),
    CONSTRAINT activity_log_outcome_check CHECK ((outcome = ANY (ARRAY['success'::text, 'failed'::text])))
);


--
-- Name: COLUMN activity_log.error_code; Type: COMMENT; Schema: battery_itops; Owner: -
--

COMMENT ON COLUMN battery_itops.activity_log.error_code IS 'error.code of a failed request (bess_common/errors.py)';


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
-- Name: activity_log activity_log_pkey; Type: CONSTRAINT; Schema: battery_itops; Owner: -
--

ALTER TABLE ONLY battery_itops.activity_log
    ADD CONSTRAINT activity_log_pkey PRIMARY KEY (activity_id);


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
-- PostgreSQL database dump complete
--

\unrestrict CjhQsQkvblu09cieKcDDanZLVnyCemiJK77hdy37aTifaRLKc5rIiTbPpbb0SCG



-- ============================================================ TimescaleDB hypertables
SET search_path = public;

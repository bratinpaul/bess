-- BESS database DDL: battery_users
-- Generated 2026-10-22 by db_docs/generate_ddl.py from database Battery
-- Sections: extensions, pg_dump schema DDL, TimescaleDB hypertables + compression, continuous aggregates,
--           views on continuous aggregates, TimescaleDB policies

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================ schema DDL (pg_dump)
--
-- PostgreSQL database dump
--

\restrict gfPl9lCPaCayz8C74ccZ1jWikbJMondmGgx1mU6SjP3guHyFm1wsatSfx3Sn1RK

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
-- Name: battery_users; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA battery_users;


SET default_tablespace = '';

SET default_table_access_method = heap;

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

\unrestrict gfPl9lCPaCayz8C74ccZ1jWikbJMondmGgx1mU6SjP3guHyFm1wsatSfx3Sn1RK



-- ============================================================ TimescaleDB hypertables
SET search_path = public;

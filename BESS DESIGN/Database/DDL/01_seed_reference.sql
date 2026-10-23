-- BESS reference data: lookup codes and RBAC roles / privileges / role grants
-- Generated 2026-10-23 by db_docs/generate_ddl.py from database Battery
-- Run after 00_create_all.sql; re-running is safe (ON CONFLICT DO NOTHING).
-- Then run backend/setup/bootstrap_auth.py (JWT keys, starter users, batch service account).

--
-- PostgreSQL database dump
--

\restrict iG2vlDEcyNfzh0jdNTUgFIKSKsDaxWhJdM9xaUD9QnOz0mCdJQWLCdrElI3Vod8

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
-- Data for Name: alarm_severity; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.alarm_severity (severity_level, severity_name) VALUES (0, 'Info') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.alarm_severity (severity_level, severity_name) VALUES (1, 'Warning') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.alarm_severity (severity_level, severity_name) VALUES (2, 'Alarm') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.alarm_severity (severity_level, severity_name) VALUES (3, 'Critical') ON CONFLICT DO NOTHING;


--
-- Data for Name: battery_chemistry; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.battery_chemistry (chemistry_code, description, nominal_cell_v, min_cell_v, max_cell_v) VALUES ('LFP', 'Lithium Iron Phosphate (LiFePO4)', 3.20, 2.50, 3.65) ON CONFLICT DO NOTHING;
INSERT INTO battery_master.battery_chemistry (chemistry_code, description, nominal_cell_v, min_cell_v, max_cell_v) VALUES ('NMC', 'Lithium Nickel Manganese Cobalt', 3.70, 3.00, 4.20) ON CONFLICT DO NOTHING;
INSERT INTO battery_master.battery_chemistry (chemistry_code, description, nominal_cell_v, min_cell_v, max_cell_v) VALUES ('LTO', 'Lithium Titanate', 2.40, 1.50, 2.80) ON CONFLICT DO NOTHING;


--
-- Data for Name: contactor_state; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.contactor_state (state_code, description) VALUES ('Open', 'DC contactors open') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.contactor_state (state_code, description) VALUES ('Closed', 'DC contactors closed') ON CONFLICT DO NOTHING;


--
-- Data for Name: ems_dispatch_mode; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.ems_dispatch_mode (mode_code, description) VALUES ('STANDBY', 'EMS active, no dispatch in progress') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.ems_dispatch_mode (mode_code, description) VALUES ('IDLE', 'EMS idle / not dispatching') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.ems_dispatch_mode (mode_code, description) VALUES ('ENERGY_ARBITRAGE', 'Charging/discharging to capture energy price spread') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.ems_dispatch_mode (mode_code, description) VALUES ('FREQUENCY_REGULATION', 'Responding to grid frequency regulation signal') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.ems_dispatch_mode (mode_code, description) VALUES ('SCHEDULED_CHARGE', 'Executing a scheduled charge plan') ON CONFLICT DO NOTHING;


--
-- Data for Name: ems_grid_service; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.ems_grid_service (service_code, description) VALUES ('NONE', 'No ancillary grid service active') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.ems_grid_service (service_code, description) VALUES ('ARBITRAGE', 'Energy price arbitrage') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.ems_grid_service (service_code, description) VALUES ('FREQ_REG', 'Frequency regulation service') ON CONFLICT DO NOTHING;


--
-- Data for Name: eol_criteria; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.eol_criteria (chemistry, soh_eol_pct, resistance_eol_pct, description) VALUES ('LFP', 70.00, 200.00, 'Capacity below 70% of BOL or resistance above 2x BOL') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.eol_criteria (chemistry, soh_eol_pct, resistance_eol_pct, description) VALUES ('NMC', 80.00, 180.00, 'Capacity below 80% of BOL or resistance above 1.8x BOL') ON CONFLICT DO NOTHING;


--
-- Data for Name: hvac_cooling_mode; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.hvac_cooling_mode (mode_code, description) VALUES ('IDLE', 'Compressor and fans off, no active cooling') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.hvac_cooling_mode (mode_code, description) VALUES ('COOLING', 'Active mechanical cooling via compressor') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.hvac_cooling_mode (mode_code, description) VALUES ('FREE_COOLING', 'Cooling via ambient/economizer without compressor') ON CONFLICT DO NOTHING;


--
-- Data for Name: market; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.market (market_id, market_code, name, currency, timezone, dam_settlement_min, rt_settlement_min, gate_closure_local, description) OVERRIDING SYSTEM VALUE VALUES (1, 'PX-DAM', 'Demo Power Exchange — Day Ahead', 'USD', 'Asia/Kolkata', 60, 15, 'D-1 10:00', 'Synthetic day-ahead + real-time market for the demo BESS') ON CONFLICT DO NOTHING;


--
-- Data for Name: operating_mode; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.operating_mode (mode_code, description) VALUES ('Standby', 'System energized, contactors closed, no active charge/discharge') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.operating_mode (mode_code, description) VALUES ('Charging', 'System actively charging') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.operating_mode (mode_code, description) VALUES ('Idle', 'System de-energized / not dispatching') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.operating_mode (mode_code, description) VALUES ('Discharging', 'System actively discharging') ON CONFLICT DO NOTHING;


--
-- Data for Name: pcs_breaker_state; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.pcs_breaker_state (state_code, description) VALUES ('CLOSED', 'AC breaker closed (connected)') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_breaker_state (state_code, description) VALUES ('OPEN', 'AC breaker open (isolated)') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_breaker_state (state_code, description) VALUES ('TRIPPED', 'Breaker tripped on protection') ON CONFLICT DO NOTHING;


--
-- Data for Name: pcs_command_type; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.pcs_command_type (command_code, description) VALUES ('SET_P', 'Set active power setpoint (kW)') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_command_type (command_code, description) VALUES ('SET_Q', 'Set reactive power setpoint (kvar)') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_command_type (command_code, description) VALUES ('SET_PF', 'Set power factor') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_command_type (command_code, description) VALUES ('SET_MODE', 'Set control mode') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_command_type (command_code, description) VALUES ('SET_SERVICE', 'Enable/disable a grid service') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_command_type (command_code, description) VALUES ('START', 'Close breaker / start conversion') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_command_type (command_code, description) VALUES ('STOP', 'Stop / open breaker') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_command_type (command_code, description) VALUES ('RESET', 'Clear latched faults') ON CONFLICT DO NOTHING;


--
-- Data for Name: pcs_grid_service; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.pcs_grid_service (service_code, description) VALUES ('NONE', 'No ancillary service active') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_grid_service (service_code, description) VALUES ('VOLT_VAR', 'Reactive power vs voltage (Q(V))') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_grid_service (service_code, description) VALUES ('VOLT_WATT', 'Active power curtailment vs voltage (P(V))') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_grid_service (service_code, description) VALUES ('FREQ_WATT', 'Active power vs frequency (P(f)) / FFR') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_grid_service (service_code, description) VALUES ('CONST_PF', 'Constant power factor') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_grid_service (service_code, description) VALUES ('CONST_Q', 'Constant reactive power') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_grid_service (service_code, description) VALUES ('PEAK_SHAVE', 'Load peak shaving') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_grid_service (service_code, description) VALUES ('BLACK_START', 'Grid-forming black start') ON CONFLICT DO NOTHING;


--
-- Data for Name: pcs_mode; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.pcs_mode (mode_code, description) VALUES ('GRID_FOLLOWING', 'Current-source; synchronizes to grid voltage/freq') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_mode (mode_code, description) VALUES ('GRID_FORMING', 'Voltage-source; sets grid voltage/freq (islanding)') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_mode (mode_code, description) VALUES ('STANDBY', 'Synchronized, breaker closed, ~zero power') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_mode (mode_code, description) VALUES ('IDLE', 'Stopped, breaker open') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_mode (mode_code, description) VALUES ('FAULT', 'Protective state, output inhibited') ON CONFLICT DO NOTHING;


--
-- Data for Name: pcs_ride_through_type; Type: TABLE DATA; Schema: battery_master; Owner: -
--

INSERT INTO battery_master.pcs_ride_through_type (rt_code, description) VALUES ('LVRT', 'Low-voltage ride-through') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_ride_through_type (rt_code, description) VALUES ('HVRT', 'High-voltage ride-through') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_ride_through_type (rt_code, description) VALUES ('LFRT', 'Low-frequency ride-through') ON CONFLICT DO NOTHING;
INSERT INTO battery_master.pcs_ride_through_type (rt_code, description) VALUES ('HFRT', 'High-frequency ride-through') ON CONFLICT DO NOTHING;


--
-- Data for Name: privilege; Type: TABLE DATA; Schema: battery_users; Owner: -
--

INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (37, 'telemetry', 'read', 'Live / forecast feed telemetry (view)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (38, 'telemetry', 'write', 'Telemetry upload / bulk load', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (11, 'fault.review', 'write', 'Fault Diagnosis > review candidates', 'system', true, NULL, '{ml}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (29, 'ml.model', 'approve', 'ML Model > set default / promote', 'system', true, NULL, '{ml}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (31, 'ml.results', 'read', 'Insights (model viewers, forecasts)', 'system', true, NULL, '{ml}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (32, 'ml.run', 'delete', 'ML Model > train / delete runs', 'system', true, NULL, '{ml}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (33, 'ml.run', 'execute', 'ML Model > train / delete runs', 'system', true, NULL, '{ml}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (4, 'audit', 'read', 'Audit log', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (23, 'master.reference', 'delete', 'Core > Reference (alarm catalog, calendar, tariff, OCV, aging, RPT)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (24, 'master.reference', 'read', 'Core > Reference (alarm catalog, calendar, tariff, OCV, aging, RPT)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (25, 'master.reference', 'write', 'Core > Reference (alarm catalog, calendar, tariff, OCV, aging, RPT)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (26, 'master.tenant', 'delete', 'Core > Actor (tenant)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (27, 'master.tenant', 'read', 'Core > Actor (tenant)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (28, 'master.tenant', 'write', 'Core > Actor (tenant)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (35, 'reports', 'read', 'Daily summary reports', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (36, 'telemetry', 'delete', 'Telemetry upload / bulk load', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (8, 'fault', 'delete', 'Core > Fault (catalog, signatures, episodes, actions)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (9, 'fault', 'read', 'Core > Fault (catalog, signatures, episodes, actions)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (10, 'fault', 'write', 'Core > Fault (catalog, signatures, episodes, actions)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (30, 'ml.model', 'write', 'ML Model > set default / promote', 'system', false, NULL, '{}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (34, 'ml.run', 'read', 'ML Model > train / delete runs', 'system', false, NULL, '{}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (12, 'kpi', 'execute', 'KPI analytics (view / recalculate)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (13, 'kpi', 'read', 'KPI analytics (view / recalculate)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (14, 'market', 'delete', 'Core > Market data & dispatch', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (15, 'market', 'read', 'Core > Market data & dispatch', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (16, 'market', 'write', 'Core > Market data & dispatch', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (17, 'master.asset', 'delete', 'Core > Asset master data (site, system, container, pack, module, PCS, EMS, HVAC)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (18, 'master.asset', 'read', 'Core > Asset master data (site, system, container, pack, module, PCS, EMS, HVAC)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (19, 'master.asset', 'write', 'Core > Asset master data (site, system, container, pack, module, PCS, EMS, HVAC)', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (20, 'master.hierarchy', 'delete', 'Core > Asset hierarchy', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (21, 'master.hierarchy', 'read', 'Core > Asset hierarchy', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (22, 'master.hierarchy', 'write', 'Core > Asset hierarchy', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (1, 'admin', 'delete', 'User & role administration', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (2, 'admin', 'read', 'User & role administration', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (3, 'admin', 'write', 'User & role administration', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (5, 'batch', 'execute', 'Batch > realtime / static / historical loads, simulator, generator', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (6, 'batch', 'read', 'Batch logs', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.privilege (privilege_id, resource, action, module_label, source, enforced, description, registered_by) OVERRIDING SYSTEM VALUE VALUES (7, 'dashboard', 'read', 'Dashboard / map / plant view', 'system', true, NULL, '{backend}') ON CONFLICT DO NOTHING;


--
-- Data for Name: role; Type: TABLE DATA; Schema: battery_users; Owner: -
--

INSERT INTO battery_users.role (role_id, role_code, role_name, is_tenant_scoped, description, is_system, version, updated_at) OVERRIDING SYSTEM VALUE VALUES (2, 'ASSET_ENGINEER', 'Asset Engineer', false, 'Maintains asset master data and fault records', false, 1, '2026-10-22 17:12:02.863264+05:30') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role (role_id, role_code, role_name, is_tenant_scoped, description, is_system, version, updated_at) OVERRIDING SYSTEM VALUE VALUES (3, 'OPERATOR', 'Operator', false, 'Monitors the plant, logs faults and reviews diagnoses', false, 1, '2026-10-22 17:12:02.863264+05:30') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role (role_id, role_code, role_name, is_tenant_scoped, description, is_system, version, updated_at) OVERRIDING SYSTEM VALUE VALUES (4, 'DATA_ENGINEER', 'Data Engineer', false, 'Loads telemetry and runs batch jobs', false, 1, '2026-10-22 17:12:02.863264+05:30') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role (role_id, role_code, role_name, is_tenant_scoped, description, is_system, version, updated_at) OVERRIDING SYSTEM VALUE VALUES (5, 'DATA_SCIENTIST', 'Data Scientist', false, 'Trains and evaluates ML models', false, 1, '2026-10-22 17:12:02.863264+05:30') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role (role_id, role_code, role_name, is_tenant_scoped, description, is_system, version, updated_at) OVERRIDING SYSTEM VALUE VALUES (6, 'ANALYST', 'Analyst', false, 'Read-only analysis and reports', false, 1, '2026-10-22 17:12:02.863264+05:30') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role (role_id, role_code, role_name, is_tenant_scoped, description, is_system, version, updated_at) OVERRIDING SYSTEM VALUE VALUES (7, 'TENANT_VIEWER', 'Tenant Viewer', true, 'Read-only, limited to the sites of its own tenant', false, 1, '2026-10-22 17:12:02.863264+05:30') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role (role_id, role_code, role_name, is_tenant_scoped, description, is_system, version, updated_at) OVERRIDING SYSTEM VALUE VALUES (1, 'ADMIN', 'Admin', false, 'Full access, user administration, approvals', true, 1, '2026-10-22 17:12:02.863264+05:30') ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role (role_id, role_code, role_name, is_tenant_scoped, description, is_system, version, updated_at) OVERRIDING SYSTEM VALUE VALUES (8, 'BATCH_SERVICE', 'Batch Service', false, 'Service accounts of the batch loaders - bulk master data and telemetry only', true, 1, '2026-10-22 17:12:02.863264+05:30') ON CONFLICT DO NOTHING;


--
-- Data for Name: role_privilege; Type: TABLE DATA; Schema: battery_users; Owner: -
--

INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 12) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 10) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 11) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 15) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 22) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 4) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 36) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 1) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 26) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 25) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 31) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 33) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 35) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 5) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 8) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 19) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 29) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 13) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 37) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 2) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 20) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 27) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 32) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 7) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 23) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 9) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 16) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 21) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 17) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 24) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 34) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 6) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 38) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 3) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 28) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 14) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (1, 18) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 27) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 25) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 24) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 12) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 10) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 7) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 9) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 31) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 11) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 6) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 19) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 15) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 22) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 13) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 21) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 37) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 35) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (2, 18) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 27) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 24) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 10) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 7) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 9) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 31) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 11) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 6) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 15) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 13) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 21) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 37) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 35) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (3, 18) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 12) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 10) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 15) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 22) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 36) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 25) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 31) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 5) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 19) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 13) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 37) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 27) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 7) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 9) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 16) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 21) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 24) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 6) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 38) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 35) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (4, 18) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 27) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 24) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 12) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 34) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 32) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 7) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 9) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 31) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 33) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 11) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 6) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 15) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 13) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 21) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 37) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 30) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 35) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (5, 18) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 27) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 24) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 7) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 9) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 31) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 15) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 13) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 21) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 37) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 35) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (6, 18) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (7, 7) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (7, 31) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (7, 13) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (7, 21) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (7, 37) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (7, 35) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (7, 18) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 27) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 28) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 18) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 19) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 21) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 22) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 37) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 38) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 6) ON CONFLICT DO NOTHING;
INSERT INTO battery_users.role_privilege (role_id, privilege_id) VALUES (8, 5) ON CONFLICT DO NOTHING;


--
-- Name: market_market_id_seq; Type: SEQUENCE SET; Schema: battery_master; Owner: -
--

SELECT pg_catalog.setval('battery_master.market_market_id_seq', 1, true);


--
-- Name: privilege_privilege_id_seq; Type: SEQUENCE SET; Schema: battery_users; Owner: -
--

SELECT pg_catalog.setval('battery_users.privilege_privilege_id_seq', 1660, true);


--
-- Name: role_role_id_seq; Type: SEQUENCE SET; Schema: battery_users; Owner: -
--

SELECT pg_catalog.setval('battery_users.role_role_id_seq', 15, true);


--
-- PostgreSQL database dump complete
--

\unrestrict iG2vlDEcyNfzh0jdNTUgFIKSKsDaxWhJdM9xaUD9QnOz0mCdJQWLCdrElI3Vod8



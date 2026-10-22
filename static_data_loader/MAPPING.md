# Static data loader

Loads `input\static\*.json` (e.g. `bess_static_data.json`) into the master tables.

| File | What it does |
|------|--------------|
| `static_load.py` | JSON → one CSV per master table, and posting each CSV to its bulk loader |
| `static_batch.py` | The batch job: every JSON in the inbox, oldest first → CSVs → load → archive → `battery_raw.batchlog` |
| `static_control.py` | Used by the backend (`/api/batch/static/...`): inbox, run now, batch log |
| `run_static_load.bat` | Run the batch by hand (`python static_batch.py -v`) |

Frontend: **Batch → Static Data Load** runs the batch and shows its batch log (job `static_data_load`).

## Flow

1. Each JSON in `input\static` is processed, oldest first.
2. The CSVs are written to `input\static\archieve\<YYYY-MM-DD>\`, using today's date. A second load on the same day goes to `<YYYY-MM-DD>_2`, and so on.
3. The CSVs are posted, parents first, to `POST /api/master-bulk/<entity>` (the backend on 127.0.0.1:8000).
4. `load_report.json` is written to that folder, and the JSON is moved into it.
5. One row is written to `battery_raw.batchlog` with `job_name = 'static_data_load'`.

The loaders upsert on `source_uuid`, the UUID from the JSON. Loading the same file again updates the records instead of duplicating them. Records created in the app have no `source_uuid`, and the loaders never touch them.

Each record also gets its `asset_hierarchy` node: tenant → site → battery system → container → pack → module, with PCS, EMS and HVAC under the battery system.

If nothing loads (bad JSON, a missing section, or every file rejected), the JSON stays in the inbox so it can be fixed. The failure is still logged. If the backend is down, nothing is moved or logged.

## Mapping

| CSV | Loader (`/api/master-bulk/…`) | From JSON | Parent column |
|-----|------|-----------|---------------|
| tenant.csv | tenant | `tenant` | – |
| site.csv | site | `sites[]` | `tenant_uuid` (from `ownership`, written to tenant_site) |
| battery_system.csv | battery_system | `sites[].battery_system` | `site_uuid` |
| battery_container.csv | battery_container | `…battery_system.container` | `battery_system_uuid` |
| battery_pack.csv | battery_pack | `…battery_system.packs[]` | `container_uuid` |
| module.csv | battery_module | `…packs[].modules[]` | `pack_uuid` |
| pcs.csv | pcs | `…battery_system.pcs` | `battery_system_uuid` |
| ems.csv | ems_controller | `…battery_system.ems` | `battery_system_uuid` |
| hvac.csv | hvac_unit | `…battery_system.hvac` | `battery_system_uuid` |

### Field by field

**tenant**
- `tenant_id` → `source_uuid`.
- `name`, `legal_name`, `tenant_type`, the address fields and `status` are copied as they are.
- `phone` and `email` come from the primary contact. The `contacts` list is not loaded.

**site**
- `site_id` → `source_uuid`.
- `site_code` is derived from `name`: upper case, with dashes (`Bhuj BESS Site` → `BHUJ-BESS-SITE`).
- `name` → `site_name`.
- `latitude` and `longitude` are copied.
- `address` is built as "city, state_province, country".
- `state_province` → `state`.
- `commissioning_date` → `commission_date`.
- `timezone` and `grid_voltage_kv` are copied.
- `rated_power_mw` and `rated_energy_mwh` are the battery system's kW and kWh divided by 1000. The site columns keep 2 decimals.
- `ownership` → `tenant_uuid`, `ownership_pct` and `is_primary_owner`.

**battery_system**
- `unit_id` → `source_uuid`.
- `serial_number` → `system_name`.
- `manufacturer` and `model` are copied.
- kW and kWh are divided by 1000 to give MW and MWh.
- `chemistry` → `chemistry_code`.
- `install_date` → `commissioned_on`.
- These values are derived:
  - `series_cells` = cells per module × modules per pack (104 × 16 = 1664).
  - `parallel_cells` = the number of packs (6).
  - `nominal_dc_voltage` = the pack nominal voltage.

**battery_container**
- `container_id` → `source_uuid`.
- `container_number` is copied.
- `type` → `container_type`.
- `ip_rating` and `fire_suppression` are copied.
- `installation_date` = the system's `install_date`.

**battery_pack**
- `pack_id` → `source_uuid`.
- `pack_number` → `<container_number>-PACK-<nn>`.
- `nominal_voltage_v` → `nominal_voltage`.
- `nominal_capacity_ah` = the modules' `capacity_ah`.
- `module_count` is copied.

**battery_module**
- `module_id` → `source_uuid`.
- `serial_number`, `capacity_ah`, `manufacture_date`, `cell_count` and `soh_pct` are copied.
- `nominal_voltage_v` → `nominal_voltage`.
- `chemistry` comes from the system, and `installation_date` is the system's `install_date`.

**pcs**
- `pcs_id` → `source_uuid`.
- `pcs_code` = `<system serial>-PCS-01`.
- `manufacturer`, `model`, `rated_power_kw` and `efficiency_pct` are copied.
- `mode` → `grid_mode`.
- `rated_ac_voltage_v` = the site's `grid_voltage_kv` × 1000.
- `commissioned_on` = the system's `install_date`.

**ems_controller**
- `ems_id` → `source_uuid`.
- `ems_code` = `<system serial>-EMS-01`.
- `manufacturer`, `model`, `firmware_version` and `control_mode` are copied.

**hvac_unit**
- `hvac_id` → `source_uuid`.
- `hvac_code` = `<system serial>-HVAC-01`.
- `manufacturer`, `model`, `cooling_capacity_kw` and `status` are copied.
- `type` → `hvac_type`.

The columns `source_uuid`, `site.grid_voltage_kv`, the container, pack, module, PCS, EMS and HVAC attribute columns were added by `backend/migrations/2026_09_29_static_master_columns.py`.

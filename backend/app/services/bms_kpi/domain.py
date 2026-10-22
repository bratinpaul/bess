"""KPI domains: what differs between the BMS, PCS and EMS KPI calculations.

The engine (config validation, SQL builder, named queries, derived formulas, storage) is shared; a domain names the
telemetry table and its entity column (BMS: battery system, PCS: PCS unit, EMS: EMS controller = plant), the master
data the per-entity params are read from, and the result tables. Inside the engine the entity is still called "system"
(system_params, system_overrides); named queries bind :system_ids / :pcs_ids / :ems_ids and return the entity column.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from app import models

CONFIG_DIR = Path(__file__).resolve().parents[3] / "kpi_config"


@dataclass(frozen=True)
class KpiDomain:
    key: str                     # bms | pcs (CLI --domain)
    label: str                   # BMS | PCS
    config_path: Path
    telemetry_table: str
    telemetry_model: type        # ORM model: the columns a row expression may read
    entity_col: str              # entity column in the telemetry and the KPI table (system_id | pcs_id)
    entity_ids_bind: str         # array bind of named queries (system_ids | pcs_ids)
    master_from: str             # FROM clause of the per-entity params, aliases usable in system_params sql
    master_id: str               # entity id in master_from
    master_name: str             # entity display name in master_from
    entity_model: type           # ORM model of the entity (existence checks)
    kpi_table: str
    run_table: str
    run_ids_col: str             # array column of the run table (system_ids | pcs_ids)

    @property
    def query_binds(self) -> set[str]:
        return {self.entity_ids_bind, "start_ts", "end_ts", "start_date", "end_date", "tz"}

    @property
    def telemetry_columns(self) -> set[str]:
        return {c.name for c in self.telemetry_model.__table__.columns}


BMS = KpiDomain(
    key="bms",
    label="BMS",
    config_path=Path(os.getenv("BMS_KPI_CONFIG", CONFIG_DIR / "bms_kpi.yaml")),
    telemetry_table="battery_telemetry.system_telemetry",
    telemetry_model=models.SystemTelemetry,
    entity_col="system_id",
    entity_ids_bind="system_ids",
    master_from=("FROM battery_master.battery_system bs "
                 "LEFT JOIN battery_master.battery_chemistry ch ON ch.chemistry_code = bs.chemistry_code"),
    master_id="bs.battery_system_id",
    master_name="bs.system_name",
    entity_model=models.BatterySystem,
    kpi_table="battery_ml.bms_kpi",
    run_table="battery_ml.bms_kpi_run",
    run_ids_col="system_ids",
)

PCS = KpiDomain(
    key="pcs",
    label="PCS",
    config_path=Path(os.getenv("PCS_KPI_CONFIG", CONFIG_DIR / "pcs_kpi.yaml")),
    telemetry_table="battery_telemetry.pcs_telemetry",
    telemetry_model=models.PcsTelemetry,
    entity_col="pcs_id",
    entity_ids_bind="pcs_ids",
    master_from=("FROM battery_master.pcs p "
                 "JOIN battery_master.battery_system bs ON bs.battery_system_id = p.system_id"),
    master_id="p.pcs_id",
    master_name="p.pcs_code",
    entity_model=models.Pcs,
    kpi_table="battery_ml.pcs_kpi",
    run_table="battery_ml.pcs_kpi_run",
    run_ids_col="pcs_ids",
)

EMS = KpiDomain(
    key="ems",
    label="EMS",
    config_path=Path(os.getenv("EMS_KPI_CONFIG", CONFIG_DIR / "ems_kpi.yaml")),
    telemetry_table="battery_telemetry.ems_telemetry",
    telemetry_model=models.EmsTelemetry,
    entity_col="ems_id",
    entity_ids_bind="ems_ids",
    # pc = the plant's PCS units (count, Σ rated kW) for the plant rating
    master_from=("FROM battery_master.ems_controller e "
                 "LEFT JOIN battery_master.battery_system bs ON bs.battery_system_id = e.battery_system_id "
                 "LEFT JOIN LATERAL (SELECT count(*) AS n_units, sum(p.rated_power_kw) AS rated_kw "
                 "FROM battery_master.pcs p WHERE p.system_id = e.battery_system_id) pc ON TRUE"),
    master_id="e.ems_id",
    master_name="e.ems_code",
    entity_model=models.EmsController,
    kpi_table="battery_ml.ems_kpi",
    run_table="battery_ml.ems_kpi_run",
    run_ids_col="ems_ids",
)

DOMAINS = {d.key: d for d in (BMS, PCS, EMS)}

"""Which RBAC resource guards which router - the single place the backend's route permissions are defined.

Every router is included in main.py with Depends(authenticated) (deny by default) AND the dependency below, which picks
the permission from the HTTP method (GET -> <resource>:read, POST/PUT/PATCH -> :write, DELETE -> :delete) unless a path
rule says otherwise. Resources and role grants are battery_users.privilege / role_privilege (the RBAC matrix in
BESS DESIGN/BESS_Technical_Review_Recommendations.xlsx). A router missing from this map fails application start-up.
"""
from bess_common.auth import crud, permission_by_method


def rbac(name: str, rules: dict[str, str], *path_rules: tuple[str, str, str]):
    return permission_by_method(rules, tuple(path_rules), name=name)


MASTER_TENANT = rbac("master.tenant", crud("master.tenant"))
MASTER_ASSET = rbac("master.asset", crud("master.asset"))
# bulk master-data load: the tenant file needs tenant write, every other entity asset write
MASTER_BULK = rbac("master.bulk", crud("master.asset"), ("POST", r"/api/master-bulk/tenant/?$", "master.tenant:write"))
MASTER_HIERARCHY = rbac("master.hierarchy", crud("master.hierarchy"))
MASTER_REFERENCE = rbac("master.reference", crud("master.reference"))
MARKET = rbac("market", crud("market"))  # market data + arbitrage dispatch (one matrix row)
FAULT = rbac("fault", crud("fault"))
TELEMETRY = rbac("telemetry", crud("telemetry"))
KPI = rbac("kpi", {"GET": "kpi:read", "HEAD": "kpi:read", "POST": "kpi:execute"})  # POST /calculate re-runs the KPI engine
REPORTS = rbac("reports", {"GET": "reports:read", "HEAD": "reports:read"})
DASHBOARD = rbac("dashboard", {"GET": "dashboard:read", "HEAD": "dashboard:read"})
BATCH = rbac("batch", {"GET": "batch:read", "HEAD": "batch:read", "POST": "batch:execute"})
AUDIT = rbac("audit", {"GET": "audit:read", "HEAD": "audit:read"})  # activity log viewer

# router module name (app.routers.<name>) -> dependency
BY_MODULE = {
    "tenant": MASTER_TENANT,
    "site": MASTER_ASSET, "battery_system": MASTER_ASSET, "battery_container": MASTER_ASSET, "battery_pack": MASTER_ASSET,
    "battery_module": MASTER_ASSET, "pcs": MASTER_ASSET, "ems_hvac": MASTER_ASSET, "battery_chemistry": MASTER_ASSET,
    "master_bulk": MASTER_BULK,
    "asset_hierarchy": MASTER_HIERARCHY,
    "alarm_catalog": MASTER_REFERENCE, "tariff_period": MASTER_REFERENCE, "calendar_day": MASTER_REFERENCE,
    "ocv_curve": MASTER_REFERENCE, "current_sensor_cal": MASTER_REFERENCE, "soc_reference": MASTER_REFERENCE,
    "aging_snapshot": MASTER_REFERENCE, "capacity_test": MASTER_REFERENCE, "lifecycle_event": MASTER_REFERENCE,
    "battery_provenance": MASTER_REFERENCE,
    "dam_price": MARKET, "rt_price": MARKET, "as_price": MARKET, "price_forecast": MARKET, "arb_common": MARKET,
    "arb_optimization_run": MARKET, "arb_decision_state": MARKET, "arb_dispatch_schedule": MARKET,
    "arb_dispatch_outcome": MARKET, "arb_as_award": MARKET, "arb_price_scenario": MARKET,
    "fault_tables": FAULT,
    "system_telemetry": TELEMETRY, "pcs_telemetry": TELEMETRY, "ems_telemetry": TELEMETRY, "hvac_telemetry": TELEMETRY,
    "module_telemetry": TELEMETRY, "demand_telemetry": TELEMETRY, "weather": TELEMETRY, "weather_forecast": TELEMETRY,
    "alarm_event": TELEMETRY, "dispatch_event": TELEMETRY,
    "bms_kpi": KPI, "pcs_kpi": KPI, "ems_kpi": KPI,
    "analytics": REPORTS, "pcs_analytics": REPORTS, "ems_analytics": REPORTS, "hvac_analytics": REPORTS,
    "dashboard": DASHBOARD, "operations": DASHBOARD,
    "batch": BATCH,
    "activity_log": AUDIT,
}


def for_module(module) -> object:
    name = module.__name__.rsplit(".", 1)[-1]
    if name not in BY_MODULE:
        raise RuntimeError(f"Router app.routers.{name} has no RBAC resource - add it to app/auth/rbac_map.py")
    return BY_MODULE[name]

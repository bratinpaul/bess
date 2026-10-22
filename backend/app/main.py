from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bess_common.observability import RequestContextMiddleware, enable_activity_log, setup_logging

setup_logging("backend")  # JSON lines to stdout + logs/backend/backend.log, before anything else logs

from app.auth import authenticated, rbac_map
from app.database import engine
from bess_common.tenant import ScopeResolver, TenantResponseFilter, tenant_guard
from app.auth import router as auth_router
from app.auth import signup as auth_signup
from app.routers import (
    activity_log,
    alarm_catalog,
    alarm_event,
    analytics,
    batch,
    asset_hierarchy,
    battery_chemistry,
    battery_container,
    battery_module,
    battery_pack,
    battery_system,
    dashboard,
    demand_telemetry,
    dispatch_event,
    ems_analytics,
    ems_hvac,
    ems_telemetry,
    hvac_analytics,
    hvac_telemetry,
    master_bulk,
    module_telemetry,
    operations,
    pcs,
    pcs_analytics,
    pcs_telemetry,
    site,
    system_telemetry,
    bms_kpi,
    pcs_kpi,
    ems_kpi,
    tariff_period,
    tenant,
    weather,
    weather_forecast,
    calendar_day,
    dam_price,
    as_price,
    rt_price,
    price_forecast,
    arb_common,
    arb_optimization_run,
    arb_decision_state,
    arb_dispatch_schedule,
    arb_dispatch_outcome,
    arb_as_award,
    arb_price_scenario,
    aging_snapshot,
    capacity_test,
    lifecycle_event,
    battery_provenance,
    ocv_curve,
    current_sensor_cal,
    soc_reference,
    fault_tables,
)

app = FastAPI(title="BESS Master Data API")

routers = [
    activity_log,
    batch,
    alarm_catalog,
    tariff_period,
    alarm_event,
    dispatch_event,
    asset_hierarchy,
    tenant,
    site,
    battery_chemistry,
    battery_system,
    battery_container,
    battery_pack,
    battery_module,
    pcs,
    master_bulk,
    dashboard,
    system_telemetry,
    bms_kpi,
    pcs_kpi,
    ems_kpi,
    pcs_telemetry,
    analytics,
    pcs_analytics,
    operations,
    ems_telemetry,
    ems_analytics,
    hvac_telemetry,
    hvac_analytics,
    module_telemetry,
    demand_telemetry,
    weather,
    weather_forecast,
    calendar_day,
    dam_price,
    as_price,
    rt_price,
    price_forecast,
    arb_common,
    arb_optimization_run,
    arb_decision_state,
    arb_dispatch_schedule,
    arb_dispatch_outcome,
    arb_as_award,
    arb_price_scenario,
    aging_snapshot,
    capacity_test,
    lifecycle_event,
    battery_provenance,
    ocv_curve,
    current_sensor_cal,
    soc_reference,
    fault_tables,
]
# tenant-scoped callers (Tenant Viewer): ids outside the tenant answer 404, GET JSON responses are narrowed to the tenant
TENANT_SCOPE = ScopeResolver(engine)
TENANT_GUARD = tenant_guard(TENANT_SCOPE)
app.add_middleware(TenantResponseFilter, resolver=TENANT_SCOPE, exclude=("/api/auth",))


# deny by default: every data router needs a valid bearer token AND the RBAC permission of its resource for the request
# method (app/auth/rbac_map.py); only /api/auth/* (login, refresh, revoke, password policy) and /api/health are public
def protected(module):
    return [Depends(authenticated), Depends(rbac_map.for_module(module)), Depends(TENANT_GUARD)]


for module in routers:
    app.include_router(module.router, dependencies=protected(module))
for module, extra in ((ems_hvac, ems_hvac.ems_router), (ems_hvac, ems_hvac.hvac_router), (batch, batch.simulator),
                      (batch, batch.static), (batch, batch.historical), (batch, batch.history_generator)):
    app.include_router(extra, dependencies=protected(module))
app.include_router(auth_router.router)
app.include_router(auth_signup.router)  # public sign-up + admin review of access requests


# ---------------------------------------------------------------- observability
def classify(method: str, path: str):
    """Requests logged as operations (start / end / duration / row counts): bulk loads and batch runs."""
    if method != "POST":
        return None
    if path.endswith("/bulk"):
        return "load", path.removeprefix("/api/").removesuffix("/bulk").replace("/", "_") + "_bulk"
    if path.startswith("/api/master-bulk/"):
        return "load", "master_bulk_" + path.rsplit("/", 1)[-1]
    if path.startswith("/api/batch/") and path.endswith("/run"):
        return "load", "batch_" + path.split("/")[3]
    return None  # KPI runs are logged inside the KPI engine (services/bms_kpi/calculator.py) with their row counts


enable_activity_log(engine)
# request id / access log / activity log inside CORS, so even its own error replies carry the CORS headers
app.add_middleware(RequestContextMiddleware, classify=classify)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://localhost:4300"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}

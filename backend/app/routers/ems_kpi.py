"""EMS KPIs per EMS controller (plant): kpi_config/ems_kpi.yaml, /api/ems-kpi (entity parameter ems_id)."""
from app.routers.kpi_router import make_router
from app.services.bms_kpi.domain import EMS

router = make_router(EMS, "/api/ems-kpi", "EMS controller")

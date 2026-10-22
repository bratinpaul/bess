"""BMS KPIs per battery system: kpi_config/bms_kpi.yaml, /api/bms-kpi (entity parameter system_id)."""
from app.routers.kpi_router import make_router
from app.services.bms_kpi.domain import BMS

router = make_router(BMS, "/api/bms-kpi", "Battery system")

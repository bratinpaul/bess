"""PCS KPIs per PCS unit: kpi_config/pcs_kpi.yaml, /api/pcs-kpi (entity parameter pcs_id)."""
from app.routers.kpi_router import make_router
from app.services.bms_kpi.domain import PCS

router = make_router(PCS, "/api/pcs-kpi", "PCS unit")

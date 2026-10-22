from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Numeric

from app.database import Base


class ModuleTelemetry(Base):
    """Per-module BMS readings (TimescaleDB hypertable, one row per module per sample)."""

    __tablename__ = "module_telemetry"

    module_id = Column(BigInteger, ForeignKey("battery_module.module_id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    cell_v_avg_v = Column(Numeric)
    cell_v_min_v = Column(Numeric)
    cell_v_max_v = Column(Numeric)
    cell_temp_max_c = Column(Numeric)
    cell_temp_min_c = Column(Numeric)
    balancing_active = Column(Boolean)

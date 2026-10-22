from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, func, Numeric, Text

from app.database import Base


class DispatchEvent(Base):
    """One EMS dispatch instruction. Hypertable on `time` (effective_from); key (dispatch_id, time).

    Sign: p_setpoint_kw > 0 is charge / import, < 0 discharge / export.
    Duration, net energy (import - export) and the issued date are derived, not stored.
    """

    __tablename__ = "dispatch_event"

    dispatch_id = Column(Text, primary_key=True)
    time = Column(DateTime(timezone=True), primary_key=True)
    ems_id = Column(BigInteger, ForeignKey("ems_controller.ems_id"), nullable=False)
    battery_system_id = Column(BigInteger, ForeignKey("battery_system.battery_system_id", ondelete="SET NULL"))
    command_code = Column(Text, nullable=False)
    dispatch_mode = Column(Text, ForeignKey("ems_dispatch_mode.mode_code"), nullable=False)
    grid_service = Column(Text, ForeignKey("ems_grid_service.service_code"), nullable=False, server_default="NONE")
    source = Column(Text)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    effective_to = Column(DateTime(timezone=True))
    p_setpoint_kw = Column(Numeric, nullable=False, server_default="0")
    target_soc_pct = Column(Numeric)
    soc_start_pct = Column(Numeric)
    soc_end_pct = Column(Numeric)
    ramp_rate_kw_s = Column(Numeric)
    import_kwh = Column(Numeric, nullable=False, server_default="0")
    export_kwh = Column(Numeric, nullable=False, server_default="0")
    avg_price_mwh = Column(Numeric)
    revenue_usd = Column(Numeric)
    accepted = Column(Boolean, nullable=False, server_default="true")
    status = Column(Text, nullable=False)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

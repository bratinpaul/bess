from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Numeric, SmallInteger, Text, func

from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Pcs(Base):
    __tablename__ = "pcs"

    pcs_id = Column(BigInteger, primary_key=True)
    system_id = Column(
        BigInteger, ForeignKey("battery_system.battery_system_id", ondelete="CASCADE"), nullable=False
    )
    pcs_code = Column(Text, nullable=False)
    manufacturer = Column(Text)
    model = Column(Text)
    serial_number = Column(Text)
    topology = Column(Text)
    cooling = Column(Text)
    rated_power_kw = Column(Numeric(9, 2), nullable=False)
    rated_apparent_kva = Column(Numeric(9, 2))
    max_charge_kw = Column(Numeric(9, 2))
    max_discharge_kw = Column(Numeric(9, 2))
    rated_ac_voltage_v = Column(Numeric(8, 2), nullable=False)
    ac_frequency_hz = Column(Numeric(4, 1), nullable=False, default=50.0)
    phases = Column(SmallInteger, nullable=False, default=3)
    dc_voltage_min_v = Column(Numeric(8, 2))
    dc_voltage_max_v = Column(Numeric(8, 2))
    dc_voltage_nom_v = Column(Numeric(8, 2))
    min_power_factor = Column(Numeric(4, 3))
    grid_code = Column(Text)
    firmware = Column(Text)
    commissioned_on = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    efficiency_pct = Column(Numeric(5, 2))
    grid_mode = Column(Text)  # grid-following / grid-forming
    # the record's UUID in the source system (static data loader); upsert key of the bulk loaders
    source_uuid = Column(UUID(as_uuid=True), unique=True)

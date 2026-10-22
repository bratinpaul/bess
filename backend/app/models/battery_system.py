from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, func, Identity, Integer, Numeric, String, Text

from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class BatteryChemistry(Base):
    __tablename__ = "battery_chemistry"

    chemistry_code = Column(Text, primary_key=True)
    description = Column(Text, nullable=False)
    nominal_cell_v = Column(Numeric(4, 2), nullable=False)
    min_cell_v = Column(Numeric(4, 2), nullable=False)
    max_cell_v = Column(Numeric(4, 2), nullable=False)


class BatterySystem(Base):
    __tablename__ = "battery_system"

    battery_system_id = Column(BigInteger, Identity(), primary_key=True)
    site_id = Column(BigInteger, ForeignKey("site.site_id"), nullable=False)
    system_name = Column(String(100), nullable=False)
    manufacturer = Column(String(100))
    model = Column(String(100))
    rated_power_mw = Column(Numeric(10, 2))
    rated_energy_mwh = Column(Numeric(10, 2))
    nominal_dc_voltage = Column(Numeric(10, 2))
    status = Column(String(20))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    chemistry_code = Column(Text, ForeignKey("battery_chemistry.chemistry_code"), nullable=False)
    series_cells = Column(Integer, nullable=False)
    parallel_cells = Column(Integer, nullable=False)
    commissioned_on = Column(Date)
    bms_firmware = Column(Text)
    # the record's UUID in the source system (static data loader); upsert key of the bulk loaders
    source_uuid = Column(UUID(as_uuid=True), unique=True)

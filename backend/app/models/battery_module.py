from sqlalchemy import BigInteger, Column, Date, ForeignKey, Identity, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class BatteryModule(Base):
    __tablename__ = "battery_module"

    module_id = Column(BigInteger, Identity(), primary_key=True)
    pack_id = Column(BigInteger, ForeignKey("battery_pack.pack_id"), nullable=False)
    serial_number = Column(String(100), unique=True)
    chemistry = Column(String(50))
    nominal_voltage = Column(Numeric(10, 2))
    capacity_ah = Column(Numeric(10, 2))
    manufacture_date = Column(Date)
    installation_date = Column(Date)
    status = Column(String(20))
    cell_count = Column(Integer)
    soh_pct = Column(Numeric(5, 2))
    # the record's UUID in the source system (static data loader); upsert key of the bulk loaders
    source_uuid = Column(UUID(as_uuid=True), unique=True)

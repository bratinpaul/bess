from sqlalchemy import BigInteger, Column, ForeignKey, Identity, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class BatteryPack(Base):
    __tablename__ = "battery_pack"

    pack_id = Column(BigInteger, Identity(), primary_key=True)
    container_id = Column(BigInteger, ForeignKey("battery_container.container_id"), nullable=False)
    pack_number = Column(String(50))
    nominal_voltage = Column(Numeric(10, 2))
    nominal_capacity_ah = Column(Numeric(10, 2))
    status = Column(String(20))
    module_count = Column(Integer)
    # the record's UUID in the source system (static data loader); upsert key of the bulk loaders
    source_uuid = Column(UUID(as_uuid=True), unique=True)

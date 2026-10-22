from sqlalchemy import BigInteger, Column, Date, ForeignKey, Identity, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class BatteryContainer(Base):
    __tablename__ = "battery_container"

    container_id = Column(BigInteger, Identity(), primary_key=True)
    battery_system_id = Column(BigInteger, ForeignKey("battery_system.battery_system_id"), nullable=False)
    container_number = Column(String(50))
    manufacturer = Column(String(100))
    installation_date = Column(Date)
    status = Column(String(20))
    container_type = Column(Text)
    ip_rating = Column(Text)
    fire_suppression = Column(Text)
    # the record's UUID in the source system (static data loader); upsert key of the bulk loaders
    source_uuid = Column(UUID(as_uuid=True), unique=True)

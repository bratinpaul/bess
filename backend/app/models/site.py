from sqlalchemy import BigInteger, Column, Date, DateTime, func, Identity, Numeric, String, Text

from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Site(Base):
    __tablename__ = "site"

    site_id = Column(BigInteger, Identity(), primary_key=True)
    site_code = Column(String(50), nullable=False, unique=True)
    site_name = Column(String(200), nullable=False)
    latitude = Column(Numeric(10, 7))
    longitude = Column(Numeric(10, 7))
    address = Column(Text)
    rated_power_mw = Column(Numeric(10, 2))
    rated_energy_mwh = Column(Numeric(10, 2))
    commission_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    timezone = Column(Text, nullable=False, server_default="UTC")
    grid_operator = Column(Text)
    state = Column(Text)
    grid_voltage_kv = Column(Numeric(8, 2))
    # the record's UUID in the source system (static data loader); upsert key of the bulk loaders
    source_uuid = Column(UUID(as_uuid=True), unique=True)

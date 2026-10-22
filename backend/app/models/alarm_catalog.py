from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func, Identity, Numeric, SmallInteger, Text, UniqueConstraint

from app.database import Base

ALARM_SOURCES = ("BMS", "PCS", "HVAC", "EMS")


class AlarmSeverity(Base):
    """0 Info, 1 Warning, 2 Alarm, 3 Critical."""

    __tablename__ = "alarm_severity"

    severity_level = Column(SmallInteger, primary_key=True)
    severity_name = Column(Text, nullable=False, unique=True)


class AlarmCatalog(Base):
    """An alarm a source system can raise; identified by (source, alarm_code)."""

    __tablename__ = "alarm_catalog"
    __table_args__ = (UniqueConstraint("source", "alarm_code", name="alarm_catalog_source_code_key"),)

    alarm_catalog_id = Column(BigInteger, Identity(always=True), primary_key=True)
    alarm_code = Column(Text, nullable=False)
    source = Column(Text, nullable=False)
    alarm_type = Column(Text, nullable=False)
    severity_level = Column(SmallInteger, ForeignKey("alarm_severity.severity_level"), nullable=False)
    asset_type = Column(Text)
    description = Column(Text, nullable=False)
    probable_cause = Column(Text)
    threshold = Column(Numeric)
    unit = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

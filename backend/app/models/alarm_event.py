from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func, Numeric, SmallInteger, Text

from app.database import Base


class AlarmEvent(Base):
    """One alarm occurrence (raise -> clear). Hypertable on `time` (the start time); key (alarm_id, time).

    Source, code, type, description and probable cause come from the linked alarm_catalog entry.
    Status (Active while end_time is NULL), duration and start date are derived, not stored.
    """

    __tablename__ = "alarm_event"

    alarm_id = Column(Text, primary_key=True)
    time = Column(DateTime(timezone=True), primary_key=True)
    alarm_catalog_id = Column(BigInteger, ForeignKey("alarm_catalog.alarm_catalog_id"), nullable=False)
    severity_level = Column(SmallInteger, ForeignKey("alarm_severity.severity_level"), nullable=False)
    # the linked asset's master-data type and name (e.g. 'Pack' / '01-01-01-PACK-01');
    # only an asset that couldn't be linked keeps the type/code the source reported
    asset_type = Column(Text)
    asset_code = Column(Text)
    # the master-data record it was matched to (e.g. 'battery_pack', 1) and how: exact / fuzzy / manual
    linked_asset_type = Column(Text)
    linked_asset_id = Column(BigInteger)
    asset_match = Column(Text)
    battery_system_id = Column(BigInteger, ForeignKey("battery_system.battery_system_id", ondelete="SET NULL"))
    end_time = Column(DateTime(timezone=True))
    trigger_value = Column(Numeric)
    threshold_value = Column(Numeric)
    unit = Column(Text)
    acknowledged_by = Column(Text)
    acknowledged_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

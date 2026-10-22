from sqlalchemy import BigInteger, Column, Date, ForeignKey, Integer, Numeric, Text

from app.database import Base


class LifecycleEvent(Base):
    """Lifecycle events of the RUL fleet systems: commissioning, augmentation, module replacement, end of life,
    failure, decommissioning (battery_master)."""

    __tablename__ = "lifecycle_event"
    __table_args__ = {"schema": "battery_master"}

    event_id = Column(BigInteger, primary_key=True)
    system_id = Column(BigInteger, ForeignKey("battery_master.battery_system.battery_system_id", ondelete="CASCADE"), nullable=False)
    event_type = Column(Text, nullable=False)
    event_date = Column(Date, nullable=False)
    age_days = Column(Integer)
    soh_at_event = Column(Numeric)
    failure_mode = Column(Text)
    note = Column(Text)

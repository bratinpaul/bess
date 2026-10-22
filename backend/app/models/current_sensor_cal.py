from sqlalchemy import BigInteger, Column, Date, ForeignKey, Numeric

from app.database import Base


class CurrentSensorCal(Base):
    """Current-sensor calibration of a fleet system: offset, gain error and offset drift as found on the date."""

    __tablename__ = "current_sensor_cal"
    __table_args__ = {"schema": "battery_master"}

    system_id = Column(BigInteger, ForeignKey("battery_master.battery_system.battery_system_id", ondelete="CASCADE"), primary_key=True)
    calibrated_on = Column(Date, primary_key=True)
    offset_a = Column(Numeric)
    gain_error_pct = Column(Numeric)
    drift_a_per_day = Column(Numeric)

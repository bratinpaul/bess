from sqlalchemy import Column, Numeric, Text

from app.database import Base


class OcvCurve(Base):
    """Per-cell OCV vs SOC by chemistry, direction (charge / discharge hysteresis, or their mean) and temperature."""

    __tablename__ = "ocv_curve"
    __table_args__ = {"schema": "battery_master"}

    chemistry = Column(Text, primary_key=True)
    direction = Column(Text, primary_key=True)
    temp_c = Column(Numeric, primary_key=True)
    soc_pct = Column(Numeric, primary_key=True)
    ocv_v = Column(Numeric, nullable=False)

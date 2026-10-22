from sqlalchemy import BigInteger, Column, Date, ForeignKey, Numeric, Text

from app.database import Base


class BatteryProvenance(Base):
    """Cell provenance, batch and beginning-of-life baseline per RUL fleet system (battery_master)."""

    __tablename__ = "battery_provenance"
    __table_args__ = {"schema": "battery_master"}

    system_id = Column(BigInteger, ForeignKey("battery_master.battery_system.battery_system_id", ondelete="CASCADE"), primary_key=True)
    manufacturer = Column(Text)
    cell_model = Column(Text)
    chemistry = Column(Text, nullable=False)
    batch_lot = Column(Text)
    cell_format = Column(Text)
    build_date = Column(Date)
    nameplate_kwh = Column(Numeric)
    bol_capacity_kwh = Column(Numeric)
    bol_resistance_mohm = Column(Numeric)
    usage_cycles_per_day = Column(Numeric)
    climate_avg_temp_c = Column(Numeric)


class EolCriteria(Base):
    """End-of-life definition per chemistry (the RUL countdown target)."""

    __tablename__ = "eol_criteria"
    __table_args__ = {"schema": "battery_master"}

    chemistry = Column(Text, primary_key=True)
    soh_eol_pct = Column(Numeric, nullable=False)
    resistance_eol_pct = Column(Numeric)
    description = Column(Text)

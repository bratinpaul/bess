from sqlalchemy import BigInteger, Boolean, Column, Date, ForeignKey, Integer, Numeric, Text

from app.database import Base


class AgingSnapshot(Base):
    """Monthly aging features + RUL labels (rul_days / rul_cycles) per system; is_censored for survival models."""

    __tablename__ = "aging_snapshot"
    __table_args__ = {"schema": "battery_master"}

    system_id = Column(BigInteger, ForeignKey("battery_master.battery_system.battery_system_id", ondelete="CASCADE"), primary_key=True)
    snapshot_date = Column(Date, primary_key=True)
    age_days = Column(Integer)
    calendar_age_years = Column(Numeric)
    cum_throughput_mwh = Column(Numeric)
    equiv_full_cycles = Column(Numeric)
    avg_dod_pct = Column(Numeric)
    avg_cell_temp_c = Column(Numeric)
    days_at_high_soc = Column(Numeric)
    soh_pct = Column(Numeric)
    internal_resistance_mohm = Column(Numeric)
    rul_cycles = Column(Numeric)
    rul_days = Column(Integer)
    is_censored = Column(Boolean)
    eol_reached = Column(Boolean)

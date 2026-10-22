from sqlalchemy import BigInteger, Column, Date, ForeignKey, Integer, Numeric, Text

from app.database import Base


class CapacityTest(Base):
    """Periodic RPT capacity / resistance checkpoints of the RUL fleet systems (the SOH ground truth)."""

    __tablename__ = "capacity_test"
    __table_args__ = {"schema": "battery_master"}

    test_id = Column(BigInteger, primary_key=True)
    system_id = Column(BigInteger, ForeignKey("battery_master.battery_system.battery_system_id", ondelete="CASCADE"), nullable=False)
    test_date = Column(Date, nullable=False)
    age_days = Column(Integer)
    equiv_full_cycles = Column(Numeric)
    measured_capacity_kwh = Column(Numeric)
    soh_pct = Column(Numeric)
    internal_resistance_mohm = Column(Numeric)
    test_temp_c = Column(Numeric)
    method = Column(Text)

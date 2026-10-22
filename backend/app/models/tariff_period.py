from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, func, Identity, Numeric, SmallInteger, Text

from app.database import Base

PRICE_LEVELS = ("SUPER_OFF_PEAK", "OFF_PEAK", "SHOULDER", "SHOULDER_HIGH", "PEAK")
DAY_TYPES = ("ALL", "WEEKDAY", "WEEKEND")


class EmsTariffPeriod(Base):
    """A time-of-use band: hours [start_hour, end_hour) on a day type and season, for one EMS or (ems_id NULL) all."""

    __tablename__ = "ems_tariff_period"

    tariff_period_id = Column(BigInteger, Identity(always=True), primary_key=True)
    ems_id = Column(BigInteger, ForeignKey("ems_controller.ems_id", ondelete="CASCADE"))
    band_code = Column(Text, nullable=False)
    band_name = Column(Text, nullable=False)
    price_level = Column(Text, nullable=False)
    start_hour = Column(SmallInteger, nullable=False)
    end_hour = Column(SmallInteger, nullable=False)
    day_type = Column(Text, nullable=False, server_default="ALL")
    season = Column(Text, nullable=False, server_default="ALL")
    reference_price_mwh = Column(Numeric)
    valid_from = Column(Date)
    valid_to = Column(Date)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

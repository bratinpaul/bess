from sqlalchemy import Boolean, Column, Date, Text

from app.database import Base


class CalendarDay(Base):
    """Reference calendar: day of week, weekend / holiday flags and the day type that drives load (battery_master)."""

    __tablename__ = "calendar_day"
    __table_args__ = {"schema": "battery_master"}

    calendar_date = Column(Date, primary_key=True)
    day_of_week = Column(Text, nullable=False)
    is_weekend = Column(Boolean, nullable=False)
    is_holiday = Column(Boolean, nullable=False, default=False)
    holiday_name = Column(Text)
    day_type = Column(Text, nullable=False)

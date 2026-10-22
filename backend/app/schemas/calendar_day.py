from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WEEKEND_DAYS = {"Saturday", "Sunday"}
DayType = Literal["Weekday", "Weekend", "Holiday"]


def derive_day_type(is_weekend: bool, is_holiday: bool) -> str:
    return "Holiday" if is_holiday else "Weekend" if is_weekend else "Weekday"


class CalendarDayBase(BaseModel):
    """Only the holiday is really an input: day of week, weekend and day type follow from the date and are filled in
    when missing, and refused when they contradict it."""

    is_holiday: Optional[bool] = None
    holiday_name: Optional[str] = Field(default=None, max_length=120)
    day_of_week: Optional[str] = None
    is_weekend: Optional[bool] = None
    day_type: Optional[DayType] = None

    def complete(self, d: date) -> dict:
        name = (self.holiday_name or "").strip() or None
        is_holiday = self.is_holiday if self.is_holiday is not None else name is not None
        if name and not is_holiday:
            raise ValueError("holiday_name is given but is_holiday is false")
        dow = DAY_NAMES[d.weekday()]
        if self.day_of_week and self.day_of_week.strip().lower() != dow.lower():
            raise ValueError(f"day_of_week '{self.day_of_week}' does not match {d.isoformat()} (a {dow})")
        weekend = dow in WEEKEND_DAYS
        if self.is_weekend is not None and self.is_weekend != weekend:
            raise ValueError(f"is_weekend={self.is_weekend} does not match {d.isoformat()} (a {dow})")
        day_type = derive_day_type(weekend, is_holiday)
        if self.day_type is not None and self.day_type != day_type:
            raise ValueError(f"day_type '{self.day_type}' should be '{day_type}' (holiday wins over weekend)")
        return {"calendar_date": d, "day_of_week": dow, "is_weekend": weekend, "is_holiday": is_holiday,
                "holiday_name": name if is_holiday else None, "day_type": day_type}


class CalendarDayCreate(CalendarDayBase):
    calendar_date: date

    @model_validator(mode="after")
    def consistent(self):
        self.complete(self.calendar_date)
        return self


class CalendarDayUpdate(CalendarDayBase):
    pass


class CalendarDayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    calendar_date: date
    day_of_week: str
    is_weekend: bool
    is_holiday: bool
    holiday_name: Optional[str] = None
    day_type: str


class CalendarDayPage(BaseModel):
    items: list[CalendarDayOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int] = {}
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    missing_days: int = 0


class BulkCalendarRowError(BaseModel):
    row: int
    errors: list[str]


class BulkCalendarResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkCalendarRowError]
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    holidays: int = 0

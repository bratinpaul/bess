from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# battery_master.lifecycle_event chk_evt
EventType = Literal["COMMISSION", "AUGMENTATION", "MODULE_REPLACE", "EOL_REACHED", "FAILURE", "DECOMMISSION"]
EVENT_TYPES: tuple[str, ...] = EventType.__args__


class LifecycleEventUpdate(BaseModel):
    """The editable fields of an event (the system it belongs to is fixed)."""

    event_type: EventType
    event_date: date
    age_days: Optional[int] = Field(default=None, ge=0)
    soh_at_event: Optional[float] = Field(default=None, ge=0, le=110)
    failure_mode: Optional[str] = Field(default=None, max_length=200)
    note: Optional[str] = Field(default=None, max_length=1000)


class LifecycleEventOut(LifecycleEventUpdate):
    model_config = ConfigDict(from_attributes=True)

    event_type: str
    event_id: int
    system_id: int
    system_code: Optional[str] = None


class LifecycleEventPage(BaseModel):
    items: list[LifecycleEventOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int] = {}


class LifecycleSystem(BaseModel):
    system_id: int
    system_code: str
    events: int
    commissioned_on: Optional[date] = None
    last_event_type: Optional[str] = None
    last_event_date: Optional[date] = None

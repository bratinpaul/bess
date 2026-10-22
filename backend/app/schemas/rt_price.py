from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.dam_price import PRICE_MAX, PRICE_MIN

BLOCK_MINUTES = (5, 15, 30, 60)


class RtPriceValues(BaseModel):
    block_minutes: int = Field(default=15, description="Settlement interval length: 5, 15, 30 or 60 minutes")
    price_mwh: float = Field(ge=PRICE_MIN, le=PRICE_MAX, description="Real-time settlement price (USD/MWh)")

    @field_validator("block_minutes")
    @classmethod
    def known_block(cls, v: int) -> int:
        if v not in BLOCK_MINUTES:
            raise ValueError(f"must be one of {', '.join(map(str, BLOCK_MINUTES))}")
        return v


class RtPriceCreate(RtPriceValues):
    node_id: int
    interval_start: datetime


class RtPriceUpdate(RtPriceValues):
    pass


class RtPriceOut(BaseModel):
    node_id: int
    node_code: str
    interval_start: datetime
    block_minutes: int
    price_mwh: float
    # day-ahead price of the hour the interval falls in, and RT - DAM (what intraday deviations settle at)
    dam_price_mwh: Optional[float] = None
    spread_mwh: Optional[float] = None


class RtPriceStats(BaseModel):
    """Over the filtered range (all pages)."""

    intervals: int = 0
    first_start: Optional[datetime] = None
    last_start: Optional[datetime] = None
    avg_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    stddev_price: Optional[float] = None
    avg_spread: Optional[float] = None
    matched_dam: int = 0


class RtPricePage(BaseModel):
    items: list[RtPriceOut]
    total: int
    page: int
    page_size: int
    stats: RtPriceStats


class BulkRtPriceRowError(BaseModel):
    row: int
    errors: list[str]


class BulkRtPriceResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkRtPriceRowError]
    nodes: list[str] = []
    first_start: Optional[datetime] = None
    last_start: Optional[datetime] = None

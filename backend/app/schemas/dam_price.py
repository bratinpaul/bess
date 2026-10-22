from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# the sample prices sit around 20-120 USD/MWh; the bounds only catch unit / typing mistakes and allow negative prices
PRICE_MIN, PRICE_MAX = -1000, 20000
BLOCK_MINUTES = (5, 15, 30, 60)


class DamPriceValues(BaseModel):
    block_minutes: int = Field(default=60, description="Delivery block length: 5, 15, 30 or 60 minutes")
    price_mwh: float = Field(ge=PRICE_MIN, le=PRICE_MAX, description="Cleared energy price (USD/MWh)")
    cleared_mw: Optional[float] = Field(default=None, ge=0, le=100000, description="Cleared volume (MW)")

    @field_validator("block_minutes")
    @classmethod
    def known_block(cls, v: int) -> int:
        if v not in BLOCK_MINUTES:
            raise ValueError(f"must be one of {', '.join(map(str, BLOCK_MINUTES))}")
        return v


class DamPriceCreate(DamPriceValues):
    node_id: int
    delivery_start: datetime


class DamPriceUpdate(DamPriceValues):
    pass


class DamPriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: int
    node_code: str
    delivery_start: datetime
    block_minutes: int
    price_mwh: float
    cleared_mw: Optional[float] = None


class DamPriceStats(BaseModel):
    """Over the filtered range (all pages)."""

    blocks: int = 0
    first_start: Optional[datetime] = None
    last_start: Optional[datetime] = None
    avg_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    total_cleared_mwh: Optional[float] = None


class DamPricePage(BaseModel):
    items: list[DamPriceOut]
    total: int
    page: int
    page_size: int
    stats: DamPriceStats


class PriceNodeOut(BaseModel):
    node_id: int
    node_code: str
    name: Optional[str] = None
    node_type: Optional[str] = None
    market_code: str
    currency: str
    timezone: str
    site_id: Optional[int] = None
    site_code: Optional[str] = None
    blocks: int = 0


class BulkDamPriceRowError(BaseModel):
    row: int
    errors: list[str]


class BulkDamPriceResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkDamPriceRowError]
    nodes: list[str] = []
    first_start: Optional[datetime] = None
    last_start: Optional[datetime] = None

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# sample capacity prices sit around 3-15 USD/MW per block; the bound only catches unit / typing mistakes
PRICE_MAX = 100000
BLOCK_MINUTES = (5, 15, 30, 60)


class AsPriceValues(BaseModel):
    block_minutes: int = Field(default=60, description="Delivery block length: 5, 15, 30 or 60 minutes")
    capacity_price_mw: Optional[float] = Field(default=None, ge=0, le=PRICE_MAX,
                                               description="Capacity price (USD per MW committed)")
    performance_price: Optional[float] = Field(default=None, ge=0, le=PRICE_MAX,
                                               description="Performance / mileage price (USD per MW)")

    @field_validator("block_minutes")
    @classmethod
    def known_block(cls, v: int) -> int:
        if v not in BLOCK_MINUTES:
            raise ValueError(f"must be one of {', '.join(map(str, BLOCK_MINUTES))}")
        return v

    @model_validator(mode="after")
    def some_price(self):
        if self.capacity_price_mw is None and self.performance_price is None:
            raise ValueError("give a capacity price, a performance price or both")
        return self


class AsPriceCreate(AsPriceValues):
    product_id: int
    delivery_start: datetime


class AsPriceUpdate(AsPriceValues):
    pass


class AsPriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    product_code: str
    delivery_start: datetime
    block_minutes: int
    capacity_price_mw: Optional[float] = None
    performance_price: Optional[float] = None


class AsPriceStats(BaseModel):
    """Over the filtered range (all pages)."""

    blocks: int = 0
    first_start: Optional[datetime] = None
    last_start: Optional[datetime] = None
    avg_capacity: Optional[float] = None
    min_capacity: Optional[float] = None
    max_capacity: Optional[float] = None
    avg_performance: Optional[float] = None
    max_performance: Optional[float] = None


class AsPricePage(BaseModel):
    items: list[AsPriceOut]
    total: int
    page: int
    page_size: int
    stats: AsPriceStats


class AsProductOut(BaseModel):
    product_id: int
    product_code: str
    name: str
    direction: Optional[str] = None
    min_bid_mw: Optional[float] = None
    sustain_minutes: Optional[int] = None
    response_seconds: Optional[int] = None
    settlement: Optional[str] = None
    description: Optional[str] = None
    market_code: str
    currency: str
    blocks: int = 0


class BulkAsPriceRowError(BaseModel):
    row: int
    errors: list[str]


class BulkAsPriceResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkAsPriceRowError]
    products: list[str] = []
    first_start: Optional[datetime] = None
    last_start: Optional[datetime] = None

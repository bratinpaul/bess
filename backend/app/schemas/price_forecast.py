from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.dam_price import PRICE_MAX, PRICE_MIN

HORIZON_MAX_H = 24 * 14  # two weeks ahead; the sample runs 14-37 h (day-ahead)


class PriceForecastValues(BaseModel):
    p10_mwh: Optional[float] = Field(default=None, ge=PRICE_MIN, le=PRICE_MAX, description="Lower quantile (USD/MWh)")
    p50_mwh: float = Field(ge=PRICE_MIN, le=PRICE_MAX, description="Median / point forecast (USD/MWh)")
    p90_mwh: Optional[float] = Field(default=None, ge=PRICE_MIN, le=PRICE_MAX, description="Upper quantile (USD/MWh)")
    model: Optional[str] = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def monotone(self):
        if self.p10_mwh is not None and self.p10_mwh > self.p50_mwh:
            raise ValueError(f"p10 ({self.p10_mwh}) is above p50 ({self.p50_mwh})")
        if self.p90_mwh is not None and self.p90_mwh < self.p50_mwh:
            raise ValueError(f"p90 ({self.p90_mwh}) is below p50 ({self.p50_mwh})")
        self.model = (self.model or "").strip() or None
        return self


class PriceForecastCreate(PriceForecastValues):
    node_id: int
    issued_at: datetime
    target_ts: datetime
    horizon_h: Optional[float] = Field(default=None, description="target_ts - issued_at in hours; derived when empty")

    @model_validator(mode="after")
    def horizon(self):
        if (self.issued_at.tzinfo is None) != (self.target_ts.tzinfo is None):
            raise ValueError("give both issued_at and target_ts with a zone, or both without")
        hours = round((self.target_ts - self.issued_at).total_seconds() / 3600, 2)
        if hours <= 0:
            raise ValueError("target_ts must be after issued_at")
        if hours > HORIZON_MAX_H:
            raise ValueError(f"horizon {hours} h is beyond {HORIZON_MAX_H} h")
        if self.horizon_h is not None and abs(self.horizon_h - hours) > 0.01:
            raise ValueError(f"horizon_h {self.horizon_h} does not match target_ts - issued_at ({hours} h)")
        self.horizon_h = hours
        return self


class PriceForecastUpdate(PriceForecastValues):
    pass


class PriceForecastOut(BaseModel):
    node_id: int
    node_code: str
    issued_at: datetime
    target_ts: datetime
    horizon_h: Optional[float] = None
    p10_mwh: Optional[float] = None
    p50_mwh: float
    p90_mwh: Optional[float] = None
    model: Optional[str] = None
    # realized day-ahead price of the target hour, P50 error against it and whether it fell inside P10-P90
    actual_mwh: Optional[float] = None
    error_mwh: Optional[float] = None
    in_band: Optional[bool] = None


class PriceForecastStats(BaseModel):
    """Over the filtered range (all pages)."""

    rows: int = 0
    vintages: int = 0
    first_target: Optional[datetime] = None
    last_target: Optional[datetime] = None
    avg_p50: Optional[float] = None
    avg_band: Optional[float] = None
    matched_actual: int = 0
    mae: Optional[float] = None
    bias: Optional[float] = None
    coverage_pct: Optional[float] = None


class PriceForecastPage(BaseModel):
    items: list[PriceForecastOut]
    total: int
    page: int
    page_size: int
    stats: PriceForecastStats


class ForecastVintage(BaseModel):
    node_id: int
    node_code: str
    issued_at: datetime
    rows: int
    first_target: datetime
    last_target: datetime
    models: list[str] = []


class BulkPriceForecastRowError(BaseModel):
    row: int
    errors: list[str]


class BulkPriceForecastResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkPriceForecastRowError]
    nodes: list[str] = []
    vintages: int = 0
    first_target: Optional[datetime] = None
    last_target: Optional[datetime] = None

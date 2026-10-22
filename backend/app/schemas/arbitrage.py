"""Schemas for the arbitrage decision tables (optimization_run, decision_state, dispatch_schedule, dispatch_outcome,
as_award, price_scenario). Timestamps without a zone are plant time (Asia/Kolkata)."""
from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

PRICE = dict(ge=-1000, le=20000)
POWER = dict(ge=-100000, le=100000)          # kW, + discharge / - charge
RESOLUTIONS = (5, 15, 30, 60)
METHODS = ("MILP", "RL_POLICY", "HEURISTIC", "IMITATION", "STOCHASTIC_MILP", "MPC")
OBJECTIVES = ("ARBITRAGE", "ARBITRAGE+AS", "PEAK_SHAVE", "AS_ONLY")
SOLVER_STATUSES = ("OPTIMAL", "FEASIBLE", "TIME_LIMIT", "INFEASIBLE", "ERROR")
# the five dispatch_event.dispatch_mode values in telemetry, plus the discharge / peak-shave counterparts
MODES = ("ENERGY_ARBITRAGE", "SCHEDULED_CHARGE", "SCHEDULED_DISCHARGE", "FREQUENCY_REGULATION", "PEAK_SHAVING",
         "IDLE", "STANDBY")
MARKETS = ("DAM", "RT", "AS")
MONEY_TOL = 0.01                              # USD tolerance for net = gross - costs and gross = price x energy

T = TypeVar("T")


def _upper_in(value: Optional[str], allowed: tuple, name: str) -> Optional[str]:
    if value is None or not value.strip():
        return None
    v = value.strip().upper()
    if v not in allowed:
        raise ValueError(f"'{value}' is not a known {name} ({', '.join(allowed)})")
    return v


def _aware_pair(a: datetime, b: datetime, names: str):
    if (a.tzinfo is None) != (b.tzinfo is None):
        raise ValueError(f"give {names} all with a zone or all without")


# ---------------------------------------------------------------- shared


class RowError(BaseModel):
    row: int
    errors: list[str]


class Stat(BaseModel):
    label: str
    value: Optional[str] = None
    warn: bool = False


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    stats: list[Stat] = []


class BulkResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[RowError]
    warnings: list[str] = []
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None


class Option(BaseModel):
    id: int
    code: str
    label: Optional[str] = None


class RunOption(BaseModel):
    run_id: int
    system_id: int
    system_code: str
    issued_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    resolution_min: int


class Lookups(BaseModel):
    systems: list[Option]
    nodes: list[Option]
    products: list[Option]
    runs: list[RunOption]
    scenario_vintages: list[datetime]
    methods: list[str] = list(METHODS)
    objectives: list[str] = list(OBJECTIVES)
    solver_statuses: list[str] = list(SOLVER_STATUSES)
    modes: list[str] = list(MODES)
    markets: list[str] = list(MARKETS)
    resolutions: list[int] = list(RESOLUTIONS)


# ---------------------------------------------------------------- optimization_run


class OptimizationRunValues(BaseModel):
    issued_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    resolution_min: int = 60
    method: Optional[str] = None
    objective: Optional[str] = None
    solver_status: Optional[str] = None
    expected_profit_usd: Optional[float] = Field(default=None, ge=-1e9, le=1e9)
    solve_seconds: Optional[float] = Field(default=None, ge=0, le=1e6)

    @field_validator("resolution_min")
    @classmethod
    def known_resolution(cls, v: int) -> int:
        if v not in RESOLUTIONS:
            raise ValueError(f"must be one of {', '.join(map(str, RESOLUTIONS))}")
        return v

    @model_validator(mode="after")
    def consistent(self):
        _aware_pair(self.issued_at, self.horizon_start, "issued_at / horizon_start / horizon_end")
        _aware_pair(self.horizon_start, self.horizon_end, "issued_at / horizon_start / horizon_end")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("horizon_end must be after horizon_start")
        if self.issued_at > self.horizon_start:
            raise ValueError("issued_at must not be after horizon_start (a run plans ahead)")
        span_min = (self.horizon_end - self.horizon_start).total_seconds() / 60
        if span_min % self.resolution_min:
            raise ValueError(f"horizon ({span_min:g} min) is not a whole number of {self.resolution_min}-min steps")
        if span_min > 14 * 24 * 60:
            raise ValueError("horizon is longer than two weeks")
        self.method = _upper_in(self.method, METHODS, "method")
        self.objective = _upper_in(self.objective, OBJECTIVES, "objective")
        self.solver_status = _upper_in(self.solver_status, SOLVER_STATUSES, "solver_status")
        return self


class OptimizationRunCreate(OptimizationRunValues):
    run_id: Optional[int] = Field(default=None, ge=1, description="Keep a given id (bulk files); new id when empty")
    system_id: int


class OptimizationRunUpdate(OptimizationRunValues):
    pass


class OptimizationRunOut(BaseModel):
    run_id: int
    system_id: int
    system_code: str
    issued_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    resolution_min: int
    method: Optional[str] = None
    objective: Optional[str] = None
    solver_status: Optional[str] = None
    expected_profit_usd: Optional[float] = None
    solve_seconds: Optional[float] = None
    schedule_rows: int = 0
    has_state: bool = False
    outcome_intervals: int = 0
    realized_net_usd: Optional[float] = None


# ---------------------------------------------------------------- decision_state


class DecisionStateValues(BaseModel):
    soc_start_pct: float = Field(ge=0, le=100)
    soh_pct: Optional[float] = Field(default=None, ge=0, le=110)
    usable_energy_mwh: Optional[float] = Field(default=None, ge=0, le=100000)
    avg_cell_temp_c: Optional[float] = Field(default=None, ge=-40, le=90)
    p_charge_avail_kw: Optional[float] = Field(default=None, ge=0, le=100000)
    p_discharge_avail_kw: Optional[float] = Field(default=None, ge=0, le=100000)
    cycles_used_today: Optional[float] = Field(default=None, ge=0, le=50)
    aux_load_forecast_kw: Optional[float] = Field(default=None, ge=0, le=100000)
    reserved_mw_as: Optional[float] = Field(default=None, ge=0, le=10000)


class DecisionStateCreate(DecisionStateValues):
    run_id: int


class DecisionStateUpdate(DecisionStateValues):
    pass


class DecisionStateOut(DecisionStateValues):
    run_id: int
    system_code: str
    issued_at: datetime
    horizon_start: datetime


# ---------------------------------------------------------------- dispatch_schedule


class DispatchScheduleValues(BaseModel):
    p_setpoint_kw: float = Field(**POWER)
    soc_target_pct: Optional[float] = Field(default=None, ge=0, le=100)
    mode: Optional[str] = None
    market: Optional[str] = None
    forecast_price_mwh: Optional[float] = Field(default=None, **PRICE)

    @model_validator(mode="after")
    def enums(self):
        self.mode = _upper_in(self.mode, MODES, "mode")
        self.market = _upper_in(self.market, MARKETS, "market")
        return self


class DispatchScheduleCreate(DispatchScheduleValues):
    run_id: int
    interval_start: datetime


class DispatchScheduleUpdate(DispatchScheduleValues):
    pass


class DispatchScheduleOut(DispatchScheduleValues):
    run_id: int
    system_code: str
    interval_start: datetime
    resolution_min: int
    # realized outcome over this schedule interval (mean actual kW, net P&L) for the same run
    actual_kw: Optional[float] = None
    net_pnl_usd: Optional[float] = None


# ---------------------------------------------------------------- dispatch_outcome


class DispatchOutcomeValues(BaseModel):
    run_id: Optional[int] = None
    p_scheduled_kw: Optional[float] = Field(default=None, **POWER)
    p_actual_kw: Optional[float] = Field(default=None, **POWER)
    price_mwh: Optional[float] = Field(default=None, **PRICE)
    energy_mwh: Optional[float] = Field(default=None, ge=-1000, le=1000)
    gross_revenue_usd: Optional[float] = Field(default=None, ge=-1e7, le=1e7)
    degradation_cost_usd: Optional[float] = Field(default=None, ge=0, le=1e7)
    grid_cost_usd: Optional[float] = Field(default=None, ge=0, le=1e7)
    net_pnl_usd: Optional[float] = Field(default=None, ge=-1e7, le=1e7)

    @model_validator(mode="after")
    def money_adds_up(self):
        # derive what is missing, refuse what contradicts: gross = price x energy, net = gross - degradation - grid
        if self.gross_revenue_usd is None and self.price_mwh is not None and self.energy_mwh is not None:
            self.gross_revenue_usd = round(self.price_mwh * self.energy_mwh, 4)
        elif None not in (self.gross_revenue_usd, self.price_mwh, self.energy_mwh):
            expect = self.price_mwh * self.energy_mwh
            if abs(expect - self.gross_revenue_usd) > MONEY_TOL:
                raise ValueError(f"gross_revenue_usd {self.gross_revenue_usd} != price x energy ({expect:.4f})")
        if self.gross_revenue_usd is not None:
            costs = (self.degradation_cost_usd or 0) + (self.grid_cost_usd or 0)
            expect = self.gross_revenue_usd - costs
            if self.net_pnl_usd is None:
                self.net_pnl_usd = round(expect, 4)
            elif abs(expect - self.net_pnl_usd) > MONEY_TOL:
                raise ValueError(f"net_pnl_usd {self.net_pnl_usd} != gross - degradation - grid ({expect:.4f})")
        return self


class DispatchOutcomeCreate(DispatchOutcomeValues):
    system_id: int
    interval_start: datetime


class DispatchOutcomeUpdate(DispatchOutcomeValues):
    pass


class DispatchOutcomeOut(DispatchOutcomeValues):
    system_id: int
    system_code: str
    interval_start: datetime
    deviation_kw: Optional[float] = None


# ---------------------------------------------------------------- as_award


class AsAwardValues(BaseModel):
    delivery_end: datetime
    awarded_mw: float = Field(gt=0, le=10000)
    capacity_price_mw: Optional[float] = Field(default=None, ge=0, le=100000)
    revenue_usd: Optional[float] = Field(default=None, ge=0, le=1e8)


class AsAwardCreate(AsAwardValues):
    system_id: int
    product_id: int
    delivery_start: datetime

    @model_validator(mode="after")
    def window(self):
        _aware_pair(self.delivery_start, self.delivery_end, "delivery_start / delivery_end")
        if self.delivery_end <= self.delivery_start:
            raise ValueError("delivery_end must be after delivery_start")
        if (self.delivery_end - self.delivery_start).total_seconds() > 7 * 86400:
            raise ValueError("an award longer than a week is not plausible")
        if self.revenue_usd is None and self.capacity_price_mw is not None:
            hours = (self.delivery_end - self.delivery_start).total_seconds() / 3600
            self.revenue_usd = round(self.awarded_mw * self.capacity_price_mw * hours, 2)
        return self


class AsAwardUpdate(AsAwardValues):
    pass


class AsAwardOut(BaseModel):
    award_id: int
    system_id: int
    system_code: str
    product_id: int
    product_code: str
    delivery_start: datetime
    delivery_end: datetime
    duration_min: float
    awarded_mw: float
    capacity_price_mw: Optional[float] = None
    revenue_usd: Optional[float] = None


# ---------------------------------------------------------------- price_scenario


class PriceScenarioValues(BaseModel):
    price_mwh: float = Field(**PRICE)
    probability: Optional[float] = Field(default=None, ge=0, le=1)


class PriceScenarioCreate(PriceScenarioValues):
    node_id: int
    issued_at: datetime
    scenario_id: int = Field(ge=1, le=10000)
    target_ts: datetime

    @model_validator(mode="after")
    def ahead(self):
        _aware_pair(self.issued_at, self.target_ts, "issued_at / target_ts")
        if self.target_ts <= self.issued_at:
            raise ValueError("target_ts must be after issued_at")
        return self


class PriceScenarioUpdate(PriceScenarioValues):
    pass


class PriceScenarioOut(PriceScenarioValues):
    node_id: int
    node_code: str
    issued_at: datetime
    scenario_id: int
    target_ts: datetime
    horizon_h: float
    # the point forecast of the same vintage / hour and the realized DAM price, for context
    forecast_p50: Optional[float] = None
    actual_mwh: Optional[float] = None

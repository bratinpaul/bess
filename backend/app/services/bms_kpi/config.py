"""Load and validate KPI definitions: backend/kpi_config/bms_kpi.yaml (BMS) and pcs_kpi.yaml (PCS) - see domain.py.

The file is re-read whenever it changes on disk, so edits apply on the next request without a restart.
Validation is strict: an unknown column, parameter, query, method, operator or KPI reference is a ConfigError naming
the KPI, so a bad edit never reaches the SQL builder.
"""
import hashlib
import re
from pathlib import Path
from typing import Any, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.services.bms_kpi import expr
from app.services.bms_kpi.domain import BMS, KpiDomain
from app.services.bms_kpi.expr import ExprError

# The columns a row expression may read mirror the domain's ORM model (so a renamed column fails validation, not the
# query); the binds every named query receives (besides the global params) are domain.query_binds.

# params every expression, formula and query can use without declaring them
BUILTIN_PARAMS = {"interval_h", "expected_samples_per_day"}

NAME = r"^[a-z][a-z0-9_]{0,62}$"


class ConfigError(Exception):
    pass


class FilterCondition(BaseModel):
    column: str  # a row expression
    op: Literal[">", ">=", "<", "<=", "=", "!=", "in", "not in"]
    # a literal, a list (in / not in), or "$name" for a global / system param
    value: Union[float, int, bool, str, list[Union[float, int, str]]]


class KpiDefinition(BaseModel):
    code: str = Field(pattern=NAME)
    name: str
    group: str
    unit: Optional[str] = None
    description: Optional[str] = None
    method: Literal["integrate", "aggregate", "counter_delta", "derived", "query"]
    column: Optional[str] = None  # row expression (integrate / aggregate / counter_delta)
    func: Optional[Literal["min", "max", "avg", "sum", "count", "first", "last"]] = None
    scale: float = 1.0
    filter: list[FilterCondition] = []
    formula: Optional[str] = None  # derived
    query: Optional[str] = None  # query: name of an entry in `queries`
    field: Optional[str] = None  # query: output column (defaults to the KPI code)
    default: Optional[float] = None  # query: value for a telemetry day the query returns nothing for
    decimals: int = Field(2, ge=0, le=6)
    summary: Literal["sum", "avg", "min", "max", "last", "formula"] = "sum"  # how the range card combines days
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")  # chart series colour (same on every chart)
    dashed: bool = False  # dashed line on line charts, e.g. a cross-check series beside its main KPI
    enabled: bool = True

    @model_validator(mode="after")
    def _method_fields(self):
        if self.method == "derived":
            if not self.formula:
                raise ValueError("method 'derived' needs a formula")
        elif self.summary == "formula":
            raise ValueError("summary 'formula' is only for derived KPIs")
        if self.method == "query":
            if not self.query:
                raise ValueError("method 'query' needs query (a name from `queries`)")
        elif self.method != "derived" and not self.column:
            raise ValueError(f"method '{self.method}' needs a column")
        if self.method == "aggregate" and not self.func:
            raise ValueError("method 'aggregate' needs func (min | max | avg | sum | count | first | last)")
        return self

    @property
    def output_field(self) -> str:
        return self.field or self.code


class IntervalConfig(BaseModel):
    mode: Literal["fixed", "actual"] = "fixed"
    minutes: float = Field(5, gt=0)
    max_gap_minutes: float = Field(15, gt=0)


class GroupDefinition(BaseModel):
    code: str = Field(pattern=NAME)
    name: str
    description: Optional[str] = None


class SystemParam(BaseModel):
    sql: str  # SQL expression over the domain's master data (BMS: battery_system bs, battery_chemistry ch;
    #           PCS: pcs p, battery_system bs)
    unit: Optional[str] = None
    description: Optional[str] = None


class QueryDefinition(BaseModel):
    description: Optional[str] = None
    sql: str  # returns system_id, kpi_date and one column per output field


class ChartDefinition(BaseModel):
    title: str
    type: Literal["bar", "line"] = "bar"
    kpis: list[str]


class KpiConfig(BaseModel):
    version: int = 1
    timezone: str = "Asia/Kolkata"
    interval: IntervalConfig = IntervalConfig()
    expected_samples_per_day: int = Field(288, gt=0)
    params: dict[str, float] = {}
    system_params: dict[str, SystemParam] = {}
    system_overrides: dict[int, dict[str, float]] = {}
    groups: list[GroupDefinition]
    queries: dict[str, QueryDefinition] = {}
    kpis: list[KpiDefinition]
    charts: list[ChartDefinition] = []
    tiles: list[str] = []  # KPI codes shown as the rollup row above the groups (range values)

    # set by load_config
    file_path: str = ""
    file_hash: str = ""

    @property
    def enabled_kpis(self) -> list[KpiDefinition]:
        return [k for k in self.kpis if k.enabled]

    @property
    def global_params(self) -> dict[str, float]:
        """`params` plus the built-ins (Δt of a fixed interval in hours, expected samples per day)."""
        return {**self.params, "interval_h": self.interval.minutes / 60.0,
                "expected_samples_per_day": float(self.expected_samples_per_day)}


def param_names(cfg: KpiConfig) -> set[str]:
    return set(cfg.global_params) | set(cfg.system_params)


def derived_order(kpis: list[KpiDefinition], params: set[str]) -> list[KpiDefinition]:
    """Derived KPIs in an order where each one's inputs come first; raises ConfigError on a cycle."""
    pending = {k.code: k for k in kpis if k.method == "derived"}
    done = {k.code for k in kpis if k.method != "derived"} | params
    ordered = []
    while pending:
        ready = [k for k in pending.values() if expr.names(k.formula, expr.FORMULA_FUNCS) <= done]
        if not ready:
            raise ConfigError("derived KPIs refer to each other in a cycle: " + ", ".join(sorted(pending)))
        for k in ready:
            ordered.append(k)
            done.add(k.code)
            del pending[k.code]
    return ordered


def range_summary(cfg: KpiConfig, daily: dict[str, list[Optional[float]]],
                  system_params: dict[str, Optional[float]]) -> dict[str, Optional[float]]:
    """One value per KPI for a range of days. summary 'formula' re-applies a derived KPI's formula to the range values
    of its inputs (e.g. Σ discharged / Σ charged), instead of combining the daily ratios."""
    out: dict[str, Optional[float]] = {}
    kpis = {k.code: k for k in cfg.enabled_kpis if k.code in daily}
    for k in kpis.values():
        v = [x for x in daily[k.code] if x is not None]
        if k.summary == "formula" or not v:
            out[k.code] = None
        elif k.summary == "sum":
            out[k.code] = sum(v)
        elif k.summary == "avg":
            out[k.code] = sum(v) / len(v)
        elif k.summary == "min":
            out[k.code] = min(v)
        elif k.summary == "max":
            out[k.code] = max(v)
        else:
            out[k.code] = v[-1]
    scope = {**cfg.global_params, **system_params}
    for k in derived_order(cfg.enabled_kpis, param_names(cfg)):
        if k.code in kpis and k.summary == "formula":
            out[k.code] = expr.evaluate(k.formula, {**scope, **out})
    return {c: (None if v is None else round(v, kpis[c].decimals)) for c, v in out.items()}


# --- validation -----------------------------------------------------------------------------------------------------

def _check_row_expr(where: str, src: str, params: set[str], columns: set[str]) -> None:
    try:
        unknown = expr.names(src, expr.ROW_FUNCS) - columns - params
    except ExprError as exc:
        raise ConfigError(f"{where}: {exc}")
    if unknown:
        raise ConfigError(f"{where}: unknown column or param {', '.join(sorted(unknown))} in '{src}'")


def _validate(cfg: KpiConfig, domain: KpiDomain) -> None:
    columns, binds = domain.telemetry_columns, domain.query_binds
    for name in list(cfg.params) + list(cfg.system_params) + list(cfg.queries):
        if not re.match(NAME, name):
            raise ConfigError(f"name '{name}' must be lower_snake_case")
    clash = BUILTIN_PARAMS & (set(cfg.params) | set(cfg.system_params))
    if clash:
        raise ConfigError("built-in param names cannot be redefined: " + ", ".join(sorted(clash)))
    clash = set(cfg.params) & set(cfg.system_params)
    if clash:
        raise ConfigError("names used as both params and system_params: " + ", ".join(sorted(clash)))
    clash = (param_names(cfg) | columns | binds) & {k.code for k in cfg.kpis}
    if clash:
        raise ConfigError("KPI codes clash with a column, param or query bind: " + ", ".join(sorted(clash)))
    clash = set(cfg.params) & binds
    if clash:
        raise ConfigError("params clash with reserved query binds: " + ", ".join(sorted(clash)))
    for sid, overrides in cfg.system_overrides.items():
        unknown = set(overrides) - set(cfg.system_params)
        if unknown:
            raise ConfigError(f"system_overrides {sid}: unknown system param(s) {', '.join(sorted(unknown))}")
    for name, q in cfg.queries.items():
        if ";" in q.sql:
            raise ConfigError(f"query '{name}' must be a single statement (no ';')")

    codes = [k.code for k in cfg.kpis]
    dupes = {c for c in codes if codes.count(c) > 1}
    if dupes:
        raise ConfigError("duplicate KPI code(s): " + ", ".join(sorted(dupes)))
    if not cfg.enabled_kpis:
        raise ConfigError("no enabled KPIs")
    groups = {g.code for g in cfg.groups}

    params = param_names(cfg)
    enabled = {k.code for k in cfg.enabled_kpis}
    for k in cfg.enabled_kpis:
        where = f"KPI '{k.code}'"
        if k.group not in groups:
            raise ConfigError(f"{where}: unknown group '{k.group}'")
        if k.method == "derived":
            try:
                used = expr.names(k.formula, expr.FORMULA_FUNCS)
            except ExprError as exc:
                raise ConfigError(f"{where}: {exc}")
            missing = used - enabled - params
            if missing:
                raise ConfigError(f"{where}: formula uses unknown or disabled KPI / param {', '.join(sorted(missing))}")
        elif k.method == "query":
            if k.query not in cfg.queries:
                raise ConfigError(f"{where}: unknown query '{k.query}'")
        else:
            _check_row_expr(where, k.column, params, columns)
        for f in k.filter:
            _check_row_expr(where + " filter", f.column, params, columns)
            if f.op in ("in", "not in") and not isinstance(f.value, list):
                raise ConfigError(f"{where}: filter op '{f.op}' needs a list value")
            if isinstance(f.value, str) and f.value.startswith("$") and f.value[1:] not in params:
                raise ConfigError(f"{where}: filter refers to unknown param '{f.value}'")
    derived_order(cfg.enabled_kpis, params)

    for chart in cfg.charts:
        unknown = set(chart.kpis) - enabled
        if unknown:
            raise ConfigError(f"chart '{chart.title}': unknown or disabled KPI(s) {', '.join(sorted(unknown))}")
    unknown = set(cfg.tiles) - enabled
    if unknown:
        raise ConfigError(f"tiles: unknown or disabled KPI(s) {', '.join(sorted(unknown))}")


_cache: dict[str, dict[str, Any]] = {}  # per domain: {"key": (path, mtime), "config": KpiConfig}


def load_config(domain: KpiDomain = BMS, path: Optional[Path] = None) -> KpiConfig:
    """Parsed + validated config of a domain; cached until the file changes."""
    path = path or domain.config_path
    cache = _cache.setdefault(domain.key, {"key": None, "config": None})
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except FileNotFoundError:
        raise ConfigError(f"KPI config file not found: {path}")
    if cache["key"] == key and cache["config"] is not None:
        return cache["config"]

    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"KPI config is not valid YAML: {exc}")
    try:
        cfg = KpiConfig.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ConfigError(f"KPI config: {where}: {first['msg']} ({len(exc.errors())} problem(s))")
    _validate(cfg, domain)
    cfg.file_path = str(path)
    cfg.file_hash = hashlib.sha256(raw).hexdigest()[:16]

    cache.update(key=key, config=cfg)
    return cfg

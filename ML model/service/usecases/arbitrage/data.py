"""Inputs of the arbitrage optimizer, all from the schema (BESS_Arbitrage_DataPack tables in battery_master):

  battery_opt_param        usable energy, SOC band, power limits, ramp, rte_ac, cycle cap, self-discharge, scalar
                           degradation cost (latest valid_from on or before the day)
  efficiency_curve         one-way efficiency by power fraction (MID SOC band) -> efficiency segments
  degradation_cost_curve   marginal $/MWh by DoD band -> DoD layers
  interconnection_limit    POI export / import caps
  grid_charge              wheeling / import duty ($/MWh) and tax (fraction of |energy value|) of the system's site
  as_product / as_price    FREQ_REG capacity price per block, minimum bid, sustain minutes
  as_award                 standing commitments (floors on the AS capacity)
  decision_state           the pack's starting state of the day (SOC, SOH-derated usable energy, available power)
  price_forecast           the day-ahead vintage (issued before the day): hourly P10 / P50 / P90
  price_scenario           the same vintage's sampled paths and weights
  rt_price / dam_price     what actually cleared (15-min / hourly) - settlement and the oracle
  dispatch_outcome         the pack's realized result (comparison, viewer)

Timestamps are plant time (Asia/Kolkata, the engine's session zone). Power sign: + discharge / − charge, like
dispatch_schedule / dispatch_outcome.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

PLANT_TZ = "Asia/Kolkata"


class ArbitrageDataError(Exception):
    """Missing inputs (the API answers 400)."""


@dataclass
class Battery:
    system_id: int
    system_name: str
    site_id: int
    usable_mwh: float
    soc_min: float
    soc_max: float
    p_charge_max_kw: float
    p_discharge_max_kw: float
    ramp_kw_per_min: Optional[float]
    rte_ac: float
    self_discharge_pct_day: float
    max_cycles_per_day: Optional[float]
    min_dwell_min: Optional[int]
    degradation_cost_mwh: float
    aux_load_kw: float
    poi_export_max_kw: float
    poi_import_max_kw: float
    charge_source: Optional[str]
    eff_curve: dict = field(default_factory=dict)   # {'CHARGE': [(fraction, eff)...], 'DISCHARGE': [...]} MID band
    deg_curve: list = field(default_factory=list)   # [(dod_band_upper_pct, $/MWh)...] ascending


@dataclass
class GridCharges:
    wheeling_mwh: float = 0.0       # $/MWh on |energy| (applies BOTH)
    import_duty_mwh: float = 0.0    # $/MWh on import
    export_duty_mwh: float = 0.0    # $/MWh on export
    tax_fraction: float = 0.0       # × |price × energy|


@dataclass
class AsInfo:
    product_id: Optional[int]
    min_bid_mw: float
    sustain_min: float


@dataclass
class DayInputs:
    day: date
    start: pd.Timestamp                      # 00:00 plant time
    hours: pd.DatetimeIndex                  # forecast hours of the day (≤ 24; the pack's last day is partial)
    issued_at: Optional[pd.Timestamp]
    p10: np.ndarray
    p50: np.ndarray
    p90: np.ndarray
    scenarios: np.ndarray                    # S × H
    scenario_probs: np.ndarray               # S
    quarters: pd.DatetimeIndex               # rt intervals of the day inside the forecast hours
    rt: np.ndarray                           # $/MWh per quarter
    dam: np.ndarray                          # $/MWh per hour (NaN when missing)
    as_price_h: np.ndarray                   # $/MW-h per hour (0 when missing)
    as_floor_h: np.ndarray                   # MW committed by standing awards, per hour (max in the hour)
    as_floor_q: np.ndarray                   # MW per quarter
    pack_run_id: Optional[int]
    pack_state: Optional[dict]               # decision_state of the pack's run of the day


def _f(v, default=None):
    return default if v is None else float(v)


def systems(engine: Engine) -> list[dict]:
    """Battery systems that have optimizer parameters, with their price node and forecast coverage."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT bs.battery_system_id AS system_id, bs.system_name, bs.site_id, s.site_name,
                   n.node_id, n.node_code,
                   (SELECT MIN(CAST(f.target_ts AS date)) FROM battery_master.price_forecast f WHERE f.node_id = n.node_id) AS first_day,
                   (SELECT MAX(CAST(f.target_ts AS date)) FROM battery_master.price_forecast f WHERE f.node_id = n.node_id) AS last_day
            FROM battery_master.battery_system bs
            JOIN battery_master.site s ON s.site_id = bs.site_id
            LEFT JOIN battery_master.price_node n ON n.site_id = bs.site_id
            WHERE EXISTS (SELECT 1 FROM battery_master.battery_opt_param p WHERE p.system_id = bs.battery_system_id)
            ORDER BY bs.system_name""")).mappings().all()
    return [dict(r) for r in rows]


def battery(engine: Engine, system_id: int, day: date) -> Battery:
    with engine.connect() as conn:
        p = conn.execute(text("""
            SELECT p.*, bs.system_name, bs.site_id FROM battery_master.battery_opt_param p
            JOIN battery_master.battery_system bs ON bs.battery_system_id = p.system_id
            WHERE p.system_id = :s AND p.valid_from <= :d ORDER BY p.valid_from DESC LIMIT 1"""),
            {"s": system_id, "d": day}).mappings().first()
        if not p:
            raise ArbitrageDataError(f"No battery_opt_param for system {system_id} on {day}")
        poi = conn.execute(text("""
            SELECT poi_export_max_kw, poi_import_max_kw, charge_source FROM battery_master.interconnection_limit
            WHERE system_id = :s AND valid_from <= :d ORDER BY valid_from DESC LIMIT 1"""),
            {"s": system_id, "d": day}).mappings().first()
        eff = conn.execute(text("""
            SELECT direction, power_fraction, AVG(one_way_eff) FILTER (WHERE soc_band = 'MID') AS mid,
                   AVG(one_way_eff) AS any_band
            FROM battery_master.efficiency_curve WHERE system_id = :s GROUP BY 1, 2 ORDER BY 1, 2"""),
            {"s": system_id}).mappings().all()
        deg = conn.execute(text("""
            SELECT dod_band_pct, marginal_cost_mwh FROM battery_master.degradation_cost_curve
            WHERE system_id = :s ORDER BY dod_band_pct"""), {"s": system_id}).all()
    curve: dict = {}
    for r in eff:
        curve.setdefault(r["direction"], []).append((float(r["power_fraction"]), float(r["mid"] or r["any_band"])))
    b = Battery(
        system_id=system_id, system_name=p["system_name"], site_id=p["site_id"],
        usable_mwh=float(p["usable_energy_mwh"]), soc_min=float(p["soc_min_pct"]), soc_max=float(p["soc_max_pct"]),
        p_charge_max_kw=float(p["p_charge_max_kw"]), p_discharge_max_kw=float(p["p_discharge_max_kw"]),
        ramp_kw_per_min=_f(p["ramp_kw_per_min"]), rte_ac=_f(p["rte_ac"], 0.9),
        self_discharge_pct_day=_f(p["self_discharge_pct_day"], 0.0), max_cycles_per_day=_f(p["max_cycles_per_day"]),
        min_dwell_min=p["min_dwell_min"], degradation_cost_mwh=_f(p["degradation_cost_mwh"], 0.0),
        aux_load_kw=_f(p["aux_load_kw"], 0.0),
        poi_export_max_kw=_f(poi["poi_export_max_kw"]) if poi else float(p["p_discharge_max_kw"]),
        poi_import_max_kw=_f(poi["poi_import_max_kw"]) if poi else float(p["p_charge_max_kw"]),
        charge_source=poi["charge_source"] if poi else None,
        eff_curve=curve, deg_curve=[(int(r[0]), float(r[1])) for r in deg])
    return b


def grid_charges(engine: Engine, site_id: int, day: date) -> GridCharges:
    """$/MWh and fraction charges of the site valid on the day (latest valid_from per charge type)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (charge_type, applies_to) charge_type, applies_to, rate, unit
            FROM battery_master.grid_charge
            WHERE site_id = :s AND (valid_from IS NULL OR valid_from <= :d)
            ORDER BY charge_type, applies_to, valid_from DESC NULLS LAST"""), {"s": site_id, "d": day}).mappings().all()
    g = GridCharges()
    for r in rows:
        rate, unit, ap = float(r["rate"]), r["unit"], r["applies_to"]
        if unit == "fraction":
            g.tax_fraction += rate
        elif unit == "$/MWh":
            if ap == "BOTH":
                g.wheeling_mwh += rate
            elif ap == "IMPORT":
                g.import_duty_mwh += rate
            elif ap == "EXPORT":
                g.export_duty_mwh += rate
        # $/kW-month demand charges are a monthly peak cost, not an energy cost - not in the daily objective
    return g


def as_info(engine: Engine) -> AsInfo:
    with engine.connect() as conn:
        r = conn.execute(text("""SELECT product_id, min_bid_mw, sustain_minutes FROM battery_master.as_product
                                 WHERE product_code = 'FREQ_REG'""")).mappings().first()
    if not r:
        return AsInfo(None, 0.0, 15.0)
    return AsInfo(r["product_id"], _f(r["min_bid_mw"], 0.0), _f(r["sustain_minutes"], 15.0))


def node_of(engine: Engine, system_id: int) -> tuple[int, str]:
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT n.node_id, n.node_code FROM battery_master.price_node n
            JOIN battery_master.battery_system bs ON bs.site_id = n.site_id
            WHERE bs.battery_system_id = :s ORDER BY n.node_id LIMIT 1"""), {"s": system_id}).first()
    if not r:
        raise ArbitrageDataError(f"Battery system {system_id} has no price node at its site")
    return int(r[0]), r[1]


def day_inputs(engine: Engine, system_id: int, node_id: int, day: date, as_product_id: Optional[int]) -> DayInputs:
    start = pd.Timestamp(datetime.combine(day, datetime.min.time())).tz_localize(PLANT_TZ)
    end = start + pd.Timedelta(days=1)
    with engine.connect() as conn:
        issued = conn.execute(text("""
            SELECT MAX(issued_at) FROM battery_master.price_forecast
            WHERE node_id = :n AND issued_at < :s AND target_ts >= :s AND target_ts < :e"""),
            {"n": node_id, "s": start, "e": end}).scalar()
        fc = pd.read_sql(text("""
            SELECT target_ts, p10_mwh, p50_mwh, p90_mwh FROM battery_master.price_forecast
            WHERE node_id = :n AND issued_at = :i AND target_ts >= :s AND target_ts < :e ORDER BY target_ts"""),
            conn, params={"n": node_id, "i": issued, "s": start, "e": end}) if issued else pd.DataFrame()
        sc = pd.read_sql(text("""
            SELECT scenario_id, target_ts, price_mwh, probability FROM battery_master.price_scenario
            WHERE node_id = :n AND issued_at = :i AND target_ts >= :s AND target_ts < :e"""),
            conn, params={"n": node_id, "i": issued, "s": start, "e": end}) if issued else pd.DataFrame()
        rt = pd.read_sql(text("""
            SELECT interval_start, price_mwh FROM battery_master.rt_price
            WHERE node_id = :n AND interval_start >= :s AND interval_start < :e ORDER BY interval_start"""),
            conn, params={"n": node_id, "s": start, "e": end})
        dam = pd.read_sql(text("""
            SELECT delivery_start, price_mwh FROM battery_master.dam_price
            WHERE node_id = :n AND delivery_start >= :s AND delivery_start < :e"""),
            conn, params={"n": node_id, "s": start, "e": end})
        asp = pd.read_sql(text("""
            SELECT delivery_start, capacity_price_mw FROM battery_master.as_price
            WHERE product_id = :p AND delivery_start >= :s AND delivery_start < :e"""),
            conn, params={"p": as_product_id, "s": start, "e": end}) if as_product_id else pd.DataFrame()
        aw = pd.read_sql(text("""
            SELECT delivery_start, delivery_end, awarded_mw FROM battery_master.as_award
            WHERE system_id = :sys AND delivery_end > :s AND delivery_start < :e"""),
            conn, params={"sys": system_id, "s": start, "e": end})
        pack = conn.execute(text("""
            SELECT r.run_id, d.soc_start_pct, d.soh_pct, d.usable_energy_mwh, d.avg_cell_temp_c, d.p_charge_avail_kw,
                   d.p_discharge_avail_kw, d.cycles_used_today, d.aux_load_forecast_kw, d.reserved_mw_as
            FROM battery_master.optimization_run r
            LEFT JOIN battery_master.decision_state d ON d.run_id = r.run_id
            WHERE r.system_id = :sys AND r.study_id IS NULL AND r.horizon_start = :s
            ORDER BY r.run_id DESC LIMIT 1"""), {"sys": system_id, "s": start}).mappings().first()
    if fc.empty:
        raise ArbitrageDataError(f"No day-ahead price forecast for {day}")

    hours = pd.DatetimeIndex(pd.to_datetime(fc["target_ts"]).dt.tz_convert(PLANT_TZ))
    H = len(hours)
    hour_pos = {h: i for i, h in enumerate(hours)}
    if not sc.empty:
        sc["target_ts"] = pd.to_datetime(sc["target_ts"]).dt.tz_convert(PLANT_TZ)
        wide = sc.pivot_table(index="scenario_id", columns="target_ts", values="price_mwh").reindex(columns=hours)
        wide = wide.fillna(pd.Series(fc["p50_mwh"].astype(float).values, index=hours))  # gaps -> P50 of the hour
        probs = sc.groupby("scenario_id")["probability"].first().reindex(wide.index).astype(float).fillna(0).values
        probs = probs / probs.sum() if probs.sum() > 0 else np.full(len(probs), 1 / len(probs))
        scen = wide.values.astype(float)
    else:
        scen, probs = fc["p50_mwh"].astype(float).values[None, :], np.array([1.0])

    rt["interval_start"] = pd.to_datetime(rt["interval_start"]).dt.tz_convert(PLANT_TZ)
    rt = rt[rt["interval_start"].dt.floor("h").isin(hours)]
    quarters = pd.DatetimeIndex(rt["interval_start"])

    def hourly(df: pd.DataFrame, col: str, fill: float) -> np.ndarray:
        out = np.full(H, fill, dtype=float)
        if not df.empty:
            for ts, v in zip(pd.to_datetime(df.iloc[:, 0]).dt.tz_convert(PLANT_TZ), df[col]):
                if ts in hour_pos and v is not None:
                    out[hour_pos[ts]] = float(v)
        return out

    floor_q = np.zeros(len(quarters))
    floor_h = np.zeros(H)
    for r in aw.itertuples():
        s, e = pd.Timestamp(r.delivery_start).tz_convert(PLANT_TZ), pd.Timestamp(r.delivery_end).tz_convert(PLANT_TZ)
        for i, q in enumerate(quarters):
            if q < e and q + pd.Timedelta(minutes=15) > s:
                floor_q[i] = max(floor_q[i], float(r.awarded_mw))
        h = s.floor("h")
        if h in hour_pos:
            floor_h[hour_pos[h]] = max(floor_h[hour_pos[h]], float(r.awarded_mw))

    state = None
    if pack and pack["soc_start_pct"] is not None:
        state = {k: (float(v) if v is not None and k != "run_id" else v) for k, v in pack.items()}
    return DayInputs(
        day=day, start=start, hours=hours, issued_at=pd.Timestamp(issued).tz_convert(PLANT_TZ) if issued else None,
        p10=fc["p10_mwh"].astype(float).values, p50=fc["p50_mwh"].astype(float).values,
        p90=fc["p90_mwh"].astype(float).values, scenarios=scen, scenario_probs=probs, quarters=quarters,
        rt=rt["price_mwh"].astype(float).values, dam=hourly(dam, "price_mwh", np.nan),
        as_price_h=hourly(asp, "capacity_price_mw", 0.0) if not asp.empty else np.zeros(H),
        as_floor_h=floor_h, as_floor_q=floor_q,
        pack_run_id=pack["run_id"] if pack else None, pack_state=state)


def pack_outcomes(engine: Engine, system_id: int, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """The pack's realized intervals (dispatch_outcome) in [start, end)."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT interval_start, run_id, p_scheduled_kw, p_actual_kw, price_mwh, energy_mwh, gross_revenue_usd,
                   degradation_cost_usd, grid_cost_usd, net_pnl_usd
            FROM battery_master.dispatch_outcome
            WHERE system_id = :s AND interval_start >= :a AND interval_start < :b ORDER BY interval_start"""),
            conn, params={"s": system_id, "a": start, "b": end})
    if not df.empty:
        df["interval_start"] = pd.to_datetime(df["interval_start"]).dt.tz_convert(PLANT_TZ)
        for c in df.columns[2:]:
            df[c] = df[c].astype(float)
    return df


def days_with_forecast(engine: Engine, node_id: int, date_from: date, date_to: date) -> list[date]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT CAST(target_ts AS date) FROM battery_master.price_forecast
            WHERE node_id = :n AND CAST(target_ts AS date) BETWEEN :a AND :b ORDER BY 1"""),
            {"n": node_id, "a": date_from, "b": date_to}).all()
    return [r[0] for r in rows]


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


def planned_open_soc(engine: Engine, system_id: int, day: date) -> Optional[float]:
    """The planned opening SOC of a day: the pack's decision_state.soc_start_pct for the run starting that day."""
    start = pd.Timestamp(datetime.combine(day, datetime.min.time())).tz_localize(PLANT_TZ)
    with engine.connect() as conn:
        v = conn.execute(text("""
            SELECT d.soc_start_pct FROM battery_master.optimization_run r
            JOIN battery_master.decision_state d ON d.run_id = r.run_id
            WHERE r.system_id = :s AND r.study_id IS NULL AND r.horizon_start = :t
            ORDER BY r.run_id DESC LIMIT 1"""), {"s": system_id, "t": start}).scalar()
    return float(v) if v is not None else None

"""Hourly market price series per EMS, the time-of-use bands and the forecast rows.

Series: ems_telemetry 5-min market_price_mwh -> hourly settlement price (mean), the hour's highest 5-min price (for
the spike label) and the grid-stress proxy (|frequency - 50 Hz|: hourly mean and max).

Forecast rows ("direct" multi-horizon): one row per EMS, forecast origin t (the last complete hour) and horizon
h = 1..H, with features known at t only:
  price history   the last 24 hourly prices, 24 h / 168 h rolling mean, volatility and max, the price at the same
                  hour on the last known day and the last week, the recent mean of the target's TOU band, spikes in
                  the last week
  calendar        target hour, day of week, weekend, month, horizon
  tou             the target's TOU band (from battery_master.ems_tariff_period) and its reference price
  stress          frequency deviation at the origin: last hour, last 24 h mean and max
Target: the hourly price at t + h; spike label: the hour's highest 5-min price above the spike threshold.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

TZ = "Asia/Kolkata"
HISTORY_H = 168  # hours of history a forecast row needs
N_LAGS = 24

FEATURE_GROUPS = {
    "history": "Price history (lags, rolling mean / volatility, same hour yesterday / last week)",
    "calendar": "Calendar (hour, day of week, weekend, month, horizon)",
    "tou": "Time-of-use band (ems_tariff_period) and its reference price",
    "stress": "Grid-stress proxy (frequency deviation)",
}
REQUIRED_GROUPS = ("history",)
LAG_COLS = [f"lag_{k}" for k in range(N_LAGS)]
GROUP_FEATURES = {
    "history": LAG_COLS + ["roll_mean_24", "roll_std_24", "roll_max_24", "roll_mean_168", "roll_std_168",
                           "same_hour_day", "same_hour_week", "band_recent_mean", "spikes_168"],
    "calendar": ["horizon", "hour", "dow", "weekend", "month", "hour_sin", "hour_cos"],
    "tou": ["band_idx", "band_ref"],
    "stress": ["fdev_1h", "fdev_24h", "fdev_max_24h"],
}
EXTERNAL_DRIVERS = ["Load / demand forecast", "Solar & wind forecast", "Weather (temperature)", "Fuel / gas price",
                    "Grid congestion & outages"]


@dataclass
class Selection:
    ems_ids: list[int]
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    feature_groups: list[str] = field(default_factory=lambda: list(FEATURE_GROUPS))
    spike_threshold: float = 150.0

    @property
    def features(self) -> list[str]:
        groups = set(self.feature_groups) | set(REQUIRED_GROUPS)
        return [f for g in FEATURE_GROUPS if g in groups for f in GROUP_FEATURES[g]] + ["ems_code"]


# ---------------------------------------------------------------- reads


def ems_units(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT e.ems_id, e.ems_code, e.battery_system_id, bs.system_name, s.site_name,
                   count(t.ts) AS readings, count(t.market_price_mwh) AS priced,
                   min(t.ts)::date AS date_from, max(t.ts)::date AS date_to,
                   avg(t.market_price_mwh) AS price_mean, max(t.market_price_mwh) AS price_max
            FROM battery_master.ems_controller e
            LEFT JOIN battery_master.battery_system bs ON bs.battery_system_id = e.battery_system_id
            LEFT JOIN battery_master.site s ON s.site_id = bs.site_id
            LEFT JOIN battery_telemetry.ems_telemetry t ON t.ems_id = e.ems_id
            GROUP BY e.ems_id, e.ems_code, e.battery_system_id, bs.system_name, s.site_name
            ORDER BY e.ems_id""")).mappings().all()
    return [{**dict(r), "date_from": r["date_from"].isoformat() if r["date_from"] else None,
             "date_to": r["date_to"].isoformat() if r["date_to"] else None,
             "price_mean": _f(r["price_mean"]), "price_max": _f(r["price_max"])} for r in rows]


def tariff(engine: Engine, ems_id: Optional[int] = None) -> list[dict]:
    """The TOU bands for an EMS (its own rows, else the shared ones), ordered by start hour."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT tariff_period_id, ems_id, band_code, band_name, price_level, start_hour, end_hour, day_type, season,
                   reference_price_mwh
            FROM battery_master.ems_tariff_period
            WHERE (valid_from IS NULL OR valid_from <= current_date) AND (valid_to IS NULL OR valid_to >= current_date)
              AND (ems_id IS NULL OR ems_id = :ems)
            ORDER BY (ems_id IS NULL), start_hour"""), {"ems": ems_id}).mappings().all()
    bands = [dict(r) for r in rows]
    own = [b for b in bands if b["ems_id"] is not None]
    out = own or [b for b in bands if b["ems_id"] is None]
    for b in out:
        b["reference_price_mwh"] = _f(b["reference_price_mwh"])
    return sorted(out, key=lambda b: b["start_hour"])


def band_lookup(bands: list[dict]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Per hour of day: band index and reference price (weekday / weekend variants fold into 'ALL' here)."""
    codes = sorted({b["band_code"] for b in bands}, key=lambda c: min(b["start_hour"] for b in bands if b["band_code"] == c))
    idx = np.full(24, -1)
    ref = np.full(24, np.nan)
    for b in bands:
        if b["day_type"] not in ("ALL", "WEEKDAY"):
            continue
        for h in range(b["start_hour"], b["end_hour"]):
            idx[h] = codes.index(b["band_code"])
            ref[h] = b["reference_price_mwh"] if b["reference_price_mwh"] is not None else np.nan
    return idx, ref, codes


def hourly(engine: Engine, ems_id: int, date_from=None, date_to=None) -> pd.DataFrame:
    """Hourly price (mean), highest 5-min price and frequency stress of one EMS, on a continuous hourly index."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT date_trunc('hour', ts) AS ts, avg(market_price_mwh) AS price, max(market_price_mwh) AS price_max5,
                   avg(abs(grid_frequency_hz - 50)) AS fdev, max(abs(grid_frequency_hz - 50)) AS fdev_max, count(*) AS n
            FROM battery_telemetry.ems_telemetry
            WHERE ems_id = :ems AND market_price_mwh IS NOT NULL
              AND (CAST(:f AS date) IS NULL OR ts >= CAST(:f AS date))
              AND (CAST(:t AS date) IS NULL OR ts < CAST(:t AS date) + 1)
            GROUP BY 1 ORDER BY 1"""), conn, params={"ems": ems_id, "f": date_from, "t": date_to})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    df = df.set_index("ts")
    for c in ("price", "price_max5", "fdev", "fdev_max"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    full = pd.date_range(df.index.min(), df.index.max(), freq="h", tz=TZ)
    df = df.reindex(full)
    df.index.name = "ts"
    df["gap"] = df["price"].isna()
    df[["price", "price_max5"]] = df[["price", "price_max5"]].interpolate(limit=3)
    df[["fdev", "fdev_max"]] = df[["fdev", "fdev_max"]].fillna(df[["fdev", "fdev_max"]].median())
    return df


def five_min(engine: Engine, ems_id: int, ts_from, ts_to) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ts, market_price_mwh FROM battery_telemetry.ems_telemetry
            WHERE ems_id = :ems AND ts >= :f AND ts < :t AND market_price_mwh IS NOT NULL ORDER BY ts"""),
            {"ems": ems_id, "f": ts_from, "t": ts_to}).all()
    return [{"ts": r[0].isoformat(), "price": float(r[1])} for r in rows]


# ---------------------------------------------------------------- rows


@dataclass
class Series:
    ems_id: int
    ts: pd.DatetimeIndex
    y: np.ndarray  # hourly price
    ymax5: np.ndarray
    fdev: np.ndarray
    fdev_max: np.ndarray
    band_idx: np.ndarray  # per hour of day
    band_ref: np.ndarray

    @classmethod
    def of(cls, ems_id: int, df: pd.DataFrame, bands: list[dict]) -> "Series":
        idx, ref, _ = band_lookup(bands)
        return cls(ems_id, df.index, df["price"].to_numpy(float), df["price_max5"].to_numpy(float),
                   df["fdev"].to_numpy(float), df["fdev_max"].to_numpy(float), idx, ref)


def rows(s: Series, origins: np.ndarray, horizon: int, spike_threshold: float, with_target: bool = True) -> pd.DataFrame:
    """Forecast rows for origin positions (index into the series; the origin hour is known) and h = 1..horizon."""
    y = s.y
    n_o = len(origins)
    hs = np.arange(1, horizon + 1)
    o = np.repeat(origins, horizon)
    h = np.tile(hs, n_o)
    tgt = o + h
    out: dict[str, np.ndarray] = {"origin_pos": o, "horizon": h.astype(float)}

    # price history at the origin
    lag_idx = o[:, None] - np.arange(N_LAGS)[None, :]
    lags = y[lag_idx]
    for k in range(N_LAGS):
        out[f"lag_{k}"] = lags[:, k]
    cs = np.concatenate([[0.0], np.cumsum(y)])
    cs2 = np.concatenate([[0.0], np.cumsum(y * y)])

    def roll(win):
        a, b = o - win + 1, o + 1
        m = (cs[b] - cs[a]) / win
        v = np.maximum((cs2[b] - cs2[a]) / win - m * m, 0)
        return m, np.sqrt(v)

    out["roll_mean_24"], out["roll_std_24"] = roll(24)
    out["roll_mean_168"], out["roll_std_168"] = roll(168)
    win24 = o[:, None] - np.arange(24)[None, :]
    out["roll_max_24"] = y[win24].max(axis=1)
    days_back = np.ceil(h / 24).astype(int) * 24
    out["same_hour_day"] = y[tgt - days_back]
    out["same_hour_week"] = y[tgt - 168]
    spike_hist = (s.ymax5 > spike_threshold).astype(float)
    cspk = np.concatenate([[0.0], np.cumsum(spike_hist)])
    out["spikes_168"] = cspk[o + 1] - cspk[o - 167]

    # target calendar and TOU band
    ts_t = s.ts[np.minimum(tgt, len(s.ts) - 1)] if with_target else _future_ts(s.ts, tgt)
    hour = ts_t.hour.to_numpy()
    out["hour"] = hour.astype(float)
    out["dow"] = ts_t.dayofweek.to_numpy().astype(float)
    out["weekend"] = (ts_t.dayofweek.to_numpy() >= 5).astype(float)
    out["month"] = ts_t.month.to_numpy().astype(float)
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["band_idx"] = s.band_idx[hour].astype(float)
    out["band_ref"] = s.band_ref[hour]
    # recent mean of the target's band: the same hours of the last 7 days (all known at the origin)
    band_hours = np.where(s.band_idx[None, :] == s.band_idx[hour][:, None], 1.0, 0.0)  # rows x 24
    hist_hour = s.ts[o].hour.to_numpy()
    back = np.arange(168)
    hh = (hist_hour[:, None] - back[None, :]) % 24
    vals = y[o[:, None] - back[None, :]]
    mask = np.take_along_axis(band_hours, hh, axis=1)
    out["band_recent_mean"] = (vals * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)

    # grid stress at the origin
    out["fdev_1h"] = s.fdev[o]
    cf = np.concatenate([[0.0], np.cumsum(s.fdev)])
    out["fdev_24h"] = (cf[o + 1] - cf[o - 23]) / 24
    out["fdev_max_24h"] = s.fdev_max[win24].max(axis=1)

    df = pd.DataFrame(out)
    df["ems_id"] = s.ems_id
    df["ems_code"] = float(s.ems_id)
    df["origin_ts"] = s.ts[o]
    df["target_ts"] = ts_t
    if with_target:
        df["y"] = y[tgt]
        df["spike"] = (s.ymax5[tgt] > spike_threshold).astype(int)
    return df


def _future_ts(ts: pd.DatetimeIndex, pos: np.ndarray) -> pd.DatetimeIndex:
    last = len(ts) - 1
    return pd.DatetimeIndex([ts[p] if p <= last else ts[last] + pd.Timedelta(hours=int(p - last)) for p in pos])


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None

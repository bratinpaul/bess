"""5-min net-load series per metering point, the weather / calendar / tariff context and the forecast rows.

Series (battery_telemetry.demand_telemetry, one metering point): net_load_kw (the target = gross load - behind-the-
meter generation), gross load and BTM generation on a continuous 5-min index (gaps up to 30 min interpolated).
Context: measured weather of the site's station (weather_actual), its forecast runs (weather_forecast: issued_at ->
hourly valid_at), the day type of each date (battery_master.calendar_day; dates it lacks fall back to Saturday /
Sunday = weekend) and the demand tariff's billing-peak window (battery_master.demand_tariff).

Forecast rows ("direct" multi-horizon): one row per metering point, origin o (the newest known reading) and step
k = 1..S (5-min steps, S = horizon hours x 12), with features known at o only:
  history   net load at the origin, last 1 h / 24 h mean, 24 h std and max; the same slot on the last known day and
            7 days back; the same slot on the last known days of the target's *day class* (workday vs weekend /
            holiday) - the newest one and the mean of the newest three (the "anchor" the boosted models correct);
            the billing-window peak of the last known day of the target's class and of the last known day
  calendar  time of day (and its sine / cosine), day of week, workday / holiday of the target day, horizon (h),
            inside the billing-peak window
  weather   temperature and GHI at the target as known at the origin - from the latest forecast run issued at or
            before it (interpolated from its hourly values), else (beyond the run, or no run) the mean of the same
            slot over the last known days, flagged by wx_forecast; the change against the anchor days' measured
            weather; the PV proxy (GHI x the site's generation per W/m², fitted on the training rows)
  btm       behind-the-meter generation at the origin and on the anchor days, gross load on the anchor days
With weather_source = 'actual' the measured weather at the target replaces the forecast (an upper bound on what a
perfect weather forecast would give - not available live).
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

TZ = "Asia/Kolkata"
STEP_MIN = 5
PER_HOUR = 12
PER_DAY = 288
HISTORY_DAYS = 7
HISTORY = HISTORY_DAYS * PER_DAY  # readings a forecast row needs before its origin
CLASS_LOOKBACK_DAYS = 14
ANCHOR_DAYS = 3

FEATURE_GROUPS = {
    "history": "Load history (lags, rolling stats, same slot yesterday / last week / last same day type, recent peaks)",
    "calendar": "Calendar (time of day / week, day type and holidays, horizon, billing window)",
    "weather": "Weather as forecast at the origin (temperature, irradiance, PV proxy)",
    "btm": "Behind-the-meter generation and gross load",
}
REQUIRED_GROUPS = ("history",)
GROUP_FEATURES = {
    "history": ["last_net", "mean_1h", "mean_24h", "std_24h", "max_24h", "same_slot_day", "same_slot_week",
                "same_slot_class", "anchor", "peak_last_class", "peak_last_day"],
    "calendar": ["horizon_h", "tod", "tod_sin", "tod_cos", "dow", "workday", "holiday", "in_window"],
    "weather": ["temp_fc", "ghi_fc", "pv_proxy_fc", "temp_delta", "ghi_delta", "wx_forecast", "temp_origin"],
    "btm": ["gen_origin", "gen_anchor", "gross_anchor"],
}
WEATHER_SOURCES = ("forecast", "actual")


@dataclass
class Selection:
    mp_ids: list[int]
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    feature_groups: list[str] = field(default_factory=lambda: list(FEATURE_GROUPS))
    weather_source: str = "forecast"
    peak_threshold_kw: Optional[float] = None  # None: the 75th percentile of the training days' billing peaks

    @property
    def features(self) -> list[str]:
        groups = set(self.feature_groups) | set(REQUIRED_GROUPS)
        return [f for g in FEATURE_GROUPS if g in groups for f in GROUP_FEATURES[g]]


# ---------------------------------------------------------------- reads


def metering_points(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT m.metering_point_id AS mp_id, m.mp_code, m.mp_type, m.voltage_kv, m.site_id, s.site_name,
                   ws.station_id, ws.station_code,
                   d.readings, d.date_from, d.date_to, d.net_mean, d.net_max,
                   (SELECT count(*) FROM battery_telemetry.weather_forecast f WHERE f.station_id = ws.station_id) AS wx_fc_values,
                   (SELECT count(DISTINCT issued_at) FROM battery_telemetry.weather_forecast f WHERE f.station_id = ws.station_id) AS wx_fc_runs
            FROM battery_master.metering_point m
            LEFT JOIN battery_master.site s ON s.site_id = m.site_id
            LEFT JOIN LATERAL (SELECT station_id, station_code FROM battery_master.weather_station w
                               WHERE w.site_id = m.site_id ORDER BY station_id LIMIT 1) ws ON true
            LEFT JOIN LATERAL (SELECT count(*) AS readings, min(ts)::date AS date_from, max(ts)::date AS date_to,
                                      avg(net_load_kw) AS net_mean, max(net_load_kw) AS net_max
                               FROM battery_telemetry.demand_telemetry t WHERE t.metering_point_id = m.metering_point_id) d ON true
            ORDER BY m.metering_point_id""")).mappings().all()
    return [{**dict(r), "voltage_kv": _f(r["voltage_kv"]), "net_mean": _f(r["net_mean"]), "net_max": _f(r["net_max"]),
             "date_from": r["date_from"].isoformat() if r["date_from"] else None,
             "date_to": r["date_to"].isoformat() if r["date_to"] else None} for r in rows]


def tariff(engine: Engine, site_id: Optional[int]) -> Optional[dict]:
    """The site's demand tariff (billing-peak window, demand charge, ratchet) valid today, else the newest."""
    if site_id is None:
        return None
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT tariff_id, name, demand_charge_per_kw, peak_window_start, peak_window_end, measurement_minutes,
                   ratchet_pct, valid_from
            FROM battery_master.demand_tariff WHERE site_id = :s
            ORDER BY (valid_from IS NULL OR valid_from <= current_date) DESC, valid_from DESC NULLS LAST LIMIT 1"""),
            {"s": site_id}).mappings().first()
    if not r:
        return None
    return {**dict(r), "demand_charge_per_kw": _f(r["demand_charge_per_kw"]),
            "peak_window_start": _f(r["peak_window_start"]), "peak_window_end": _f(r["peak_window_end"]),
            "ratchet_pct": _f(r["ratchet_pct"]), "valid_from": r["valid_from"].isoformat() if r["valid_from"] else None}


DEFAULT_WINDOW = (17.0, 22.0)


def window_of(t: Optional[dict]) -> tuple[float, float]:
    if t and t.get("peak_window_start") is not None and t.get("peak_window_end") is not None:
        return float(t["peak_window_start"]), float(t["peak_window_end"])
    return DEFAULT_WINDOW


def demand(engine: Engine, mp_id: int, date_from=None, date_to=None) -> pd.DataFrame:
    """5-min net / gross / BTM generation of one metering point on a continuous 5-min index."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT ts, net_load_kw AS net, gross_load_kw AS gross, behind_meter_gen_kw AS gen
            FROM battery_telemetry.demand_telemetry
            WHERE metering_point_id = :mp
              AND (CAST(:f AS date) IS NULL OR ts >= CAST(:f AS date))
              AND (CAST(:t AS date) IS NULL OR ts < CAST(:t AS date) + 1)
            ORDER BY ts"""), conn, params={"mp": mp_id, "f": date_from, "t": date_to})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    df = df.set_index("ts")
    for c in ("net", "gross", "gen"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    full = pd.date_range(df.index.min(), df.index.max(), freq=f"{STEP_MIN}min", tz=TZ)
    df = df.reindex(full)
    df.index.name = "ts"
    df["gap"] = df["net"].isna()
    df[["net", "gross", "gen"]] = df[["net", "gross", "gen"]].interpolate(limit=6, limit_area="inside")
    return df


def weather_actual(engine: Engine, station_id: Optional[int], ts: pd.DatetimeIndex) -> pd.DataFrame:
    out = pd.DataFrame(index=ts, columns=["temp", "ghi", "cloud"], dtype=float)
    if station_id is None or len(ts) == 0:
        return out
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT ts, temp_c AS temp, ghi_wm2 AS ghi, cloud_fraction AS cloud FROM battery_telemetry.weather_actual
            WHERE station_id = :s AND ts >= :f AND ts <= :t ORDER BY ts"""), conn,
            params={"s": station_id, "f": ts[0].to_pydatetime(), "t": ts[-1].to_pydatetime()})
    if df.empty:
        return out
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    df = df.set_index("ts").apply(pd.to_numeric, errors="coerce").astype(float)
    df = df[~df.index.duplicated()].reindex(ts)
    return df.interpolate(limit=12, limit_area="inside")


def weather_runs(engine: Engine, station_id: Optional[int]) -> list[tuple[pd.Timestamp, np.ndarray, np.ndarray, np.ndarray]]:
    """Forecast runs of a station: (issued_at, valid_at epoch seconds, temp, ghi), oldest first."""
    if station_id is None:
        return []
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT issued_at, valid_at, temp_c AS temp, ghi_wm2 AS ghi FROM battery_telemetry.weather_forecast
            WHERE station_id = :s ORDER BY issued_at, valid_at"""), conn, params={"s": station_id})
    runs = []
    for issued, g in df.groupby("issued_at", sort=True):
        v = pd.to_datetime(g["valid_at"], utc=True)
        runs.append((pd.Timestamp(issued).tz_convert(TZ), (v.astype("int64") // 10**9).to_numpy(float),
                     pd.to_numeric(g["temp"], errors="coerce").to_numpy(float),
                     pd.to_numeric(g["ghi"], errors="coerce").to_numpy(float)))
    return runs


def calendar(engine: Engine) -> dict[date, tuple[bool, bool, Optional[str]]]:
    """date -> (workday, holiday, holiday name) from battery_master.calendar_day."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT calendar_date, day_type, is_holiday, holiday_name FROM battery_master.calendar_day")).all()
    return {r[0]: (r[1] == "Weekday", bool(r[2]), r[3]) for r in rows}


# ---------------------------------------------------------------- series


@dataclass
class Series:
    mp_id: int
    t0: pd.Timestamp  # timestamp of position 0
    n: int  # known readings (positions 0..n-1)
    net: np.ndarray
    gross: np.ndarray
    gen: np.ndarray
    temp: np.ndarray  # measured weather on the same index
    ghi: np.ndarray
    runs: list
    cal: dict
    window: tuple[float, float]
    tariff: Optional[dict] = None
    station_id: Optional[int] = None
    pv_ratio: float = 0.0

    def ts(self, pos) -> pd.DatetimeIndex:
        pos = np.atleast_1d(np.asarray(pos, dtype=np.int64))
        return pd.DatetimeIndex(self.t0 + pd.to_timedelta(pos * STEP_MIN, unit="min"))

    def day_info(self, days: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """workday / holiday flags for dates (calendar_day, else the Saturday / Sunday rule)."""
        wd = np.empty(len(days), bool)
        hol = np.zeros(len(days), bool)
        for i, d in enumerate(days):
            c = self.cal.get(d)
            if c is None:
                wd[i] = d.weekday() < 5
            else:
                wd[i], hol[i] = c[0], c[1]
        return wd, hol

    @classmethod
    def build(cls, engine: Engine, mp: dict, df: pd.DataFrame, cal: dict, tariff_row: Optional[dict]) -> "Series":
        ts = df.index
        wx = weather_actual(engine, mp.get("station_id"), ts)
        return cls(mp["mp_id"], ts[0], len(ts), df["net"].to_numpy(float), df["gross"].to_numpy(float),
                   df["gen"].to_numpy(float), wx["temp"].to_numpy(float), wx["ghi"].to_numpy(float),
                   weather_runs(engine, mp.get("station_id")), cal, window_of(tariff_row), tariff_row,
                   mp.get("station_id"))

    def window_mask(self, pos: np.ndarray) -> np.ndarray:
        t = self.ts(pos)
        tod = t.hour.to_numpy() + t.minute.to_numpy() / 60
        return (tod >= self.window[0]) & (tod < self.window[1])

    def daily_peaks(self) -> pd.DataFrame:
        """Billing-window peak (kW) and its time per complete day of the known series."""
        pos = np.arange(self.n)
        m = self.window_mask(pos) & np.isfinite(self.net)
        t = self.ts(pos[m])
        df = pd.DataFrame({"date": t.date, "net": self.net[m], "ts": t})
        if df.empty:
            return pd.DataFrame(columns=["peak", "peak_ts", "n"])
        idx = df.groupby("date")["net"].idxmax()
        out = pd.DataFrame({"peak": df.loc[idx, "net"].to_numpy(), "peak_ts": df.loc[idx, "ts"].to_numpy()},
                           index=df.loc[idx, "date"].to_numpy())
        out["n"] = df.groupby("date").size().reindex(out.index).to_numpy()
        full = int((self.window[1] - self.window[0]) * PER_HOUR)
        return out[out["n"] >= full * 0.9]


def _weather_at(s: Series, origin: int, tgt: np.ndarray, source: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Temperature and GHI at the targets as known at the origin, and whether they came from a forecast run."""
    n = len(tgt)
    temp = np.full(n, np.nan)
    ghi = np.full(n, np.nan)
    from_fc = np.zeros(n)
    if source == "actual":
        ok = tgt < s.n
        temp[ok], ghi[ok] = s.temp[tgt[ok]], s.ghi[tgt[ok]]
        from_fc[ok] = 1.0
    else:
        o_ts = s.ts(origin)[0]
        run = None
        for r in s.runs:  # oldest first: keep the newest issued at or before the origin
            if r[0] <= o_ts:
                run = r
            else:
                break
        if run is not None and len(run[1]):
            sec = (s.ts(tgt).asi8 // 10**9).astype(float)
            # the run covers from an hour before its first valid hour to its last valid hour
            cover = (sec >= run[1][0] - 3600) & (sec <= run[1][-1])
            temp[cover] = np.interp(sec[cover], run[1], run[2])
            ghi[cover] = np.interp(sec[cover], run[1], run[3])
            from_fc[cover] = 1.0
    # fallback: the mean of the same slot over the last known days
    miss = ~np.isfinite(temp) | ~np.isfinite(ghi)
    if miss.any():
        back = tgt[miss][:, None] - PER_DAY * np.arange(1, 4)[None, :]
        back = back - PER_DAY * np.maximum(0, np.ceil((back - origin) / PER_DAY)).astype(int)
        back = np.clip(back, 0, s.n - 1)
        with np.errstate(all="ignore"):
            t_fb = np.nanmean(s.temp[back], axis=1)
            g_fb = np.nanmean(s.ghi[back], axis=1)
        temp[miss] = np.where(np.isfinite(temp[miss]), temp[miss], t_fb)
        ghi[miss] = np.where(np.isfinite(ghi[miss]), ghi[miss], g_fb)
    return temp, ghi, from_fc


def rows(s: Series, origins: np.ndarray, steps: int, weather_source: str = "forecast",
         with_target: bool = True) -> pd.DataFrame:
    """Forecast rows for origin positions (the origin reading is known) and steps k = 1..steps."""
    net, gross, gen = s.net, s.gross, s.gen
    n_o = len(origins)
    ks = np.arange(1, steps + 1)
    o = np.repeat(origins, steps)
    k = np.tile(ks, n_o)
    tgt = o + k
    out: dict[str, np.ndarray] = {"origin_pos": o, "step": k, "horizon_h": k / PER_HOUR}

    # history at the origin
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(net))])
    cs2 = np.concatenate([[0.0], np.cumsum(np.nan_to_num(net) ** 2)])

    def roll(win):
        a, b = o - win + 1, o + 1
        m = (cs[b] - cs[a]) / win
        return m, np.sqrt(np.maximum((cs2[b] - cs2[a]) / win - m * m, 0))

    out["last_net"] = net[o]
    out["mean_1h"], _ = roll(PER_HOUR)
    out["mean_24h"], out["std_24h"] = roll(PER_DAY)
    # 24 h max per origin (origins repeat: compute once)
    mx = {int(p): float(np.nanmax(net[p - PER_DAY + 1:p + 1])) for p in origins}
    out["max_24h"] = np.array([mx[int(p)] for p in o])
    days_back = np.ceil(k / PER_DAY).astype(int) * PER_DAY
    out["same_slot_day"] = net[tgt - days_back]
    out["same_slot_week"] = net[tgt - 7 * PER_DAY]

    # day class of every target and candidate day
    t_ts = s.ts(tgt)
    t_dates = np.array(t_ts.date)
    uniq = np.unique(t_dates)
    span = pd.date_range(min(uniq) - pd.Timedelta(days=CLASS_LOOKBACK_DAYS), max(uniq), freq="D").date
    wd_all, hol_all = s.day_info(np.array(span))
    wd_of = dict(zip(span, wd_all))
    hol_of = dict(zip(span, hol_all))
    workday = np.array([wd_of[d] for d in t_dates])
    out["workday"] = workday.astype(float)
    out["holiday"] = np.array([hol_of[d] for d in t_dates]).astype(float)

    # same slot on the newest known days of the same class
    matches = np.full((len(tgt), ANCHOR_DAYS), -1, dtype=np.int64)
    found = np.zeros(len(tgt), dtype=int)
    for back in range(1, CLASS_LOOKBACK_DAYS + 1):
        p = tgt - back * PER_DAY
        cand_dates = np.array(s.ts(p).date)
        cls = np.array([wd_of.get(d, d.weekday() < 5) for d in cand_dates])
        ok = (p <= o) & (p >= 0) & (cls == workday) & (found < ANCHOR_DAYS)
        idx = np.where(ok)[0]
        matches[idx, found[idx]] = p[idx]
        found[idx] += 1
        if (found >= ANCHOR_DAYS).all():
            break
    first = np.where(matches[:, 0] >= 0, matches[:, 0], tgt - days_back)
    out["same_slot_class"] = net[first]
    valid = matches >= 0
    safe = np.where(valid, matches, 0)

    def anchor_mean(arr):
        vals = np.where(valid, arr[safe], np.nan)
        with np.errstate(all="ignore"):
            m = np.nanmean(vals, axis=1)
        return np.where(np.isfinite(m), m, arr[first])

    out["anchor"] = anchor_mean(net)
    out["gross_anchor"] = anchor_mean(gross)
    out["gen_anchor"] = anchor_mean(gen)
    out["gen_origin"] = gen[o]

    # billing-window peaks known at the origin (the day's window over)
    peaks = s.daily_peaks()
    peak_of = dict(zip(peaks.index, peaks["peak"]))
    end_h = s.window[1]
    o_ts_all = s.ts(origins)
    last_class_peak, last_day_peak = {}, {}
    for oi, (op, ots) in enumerate(zip(origins, o_ts_all)):
        for d in np.unique(t_dates[o == op]):
            lc = ld = np.nan
            for back in range(1, CLASS_LOOKBACK_DAYS + 1):
                dd = (pd.Timestamp(d) - pd.Timedelta(days=back)).date()
                end = pd.Timestamp(dd).tz_localize(TZ) + pd.Timedelta(hours=end_h)
                if end > ots or dd not in peak_of:
                    continue
                if not np.isfinite(ld):
                    ld = peak_of[dd]
                if wd_of.get(dd, dd.weekday() < 5) == wd_of[d]:
                    lc = peak_of[dd]
                    break
            # the origin's own day counts when its window is already over
            last_class_peak[(int(op), d)] = lc
            last_day_peak[(int(op), d)] = ld
    out["peak_last_class"] = np.array([last_class_peak[(int(a), b)] for a, b in zip(o, t_dates)])
    out["peak_last_day"] = np.array([last_day_peak[(int(a), b)] for a, b in zip(o, t_dates)])

    # calendar of the target
    hour = t_ts.hour.to_numpy()
    tod = hour + t_ts.minute.to_numpy() / 60
    out["tod"] = tod
    out["tod_sin"] = np.sin(2 * np.pi * tod / 24)
    out["tod_cos"] = np.cos(2 * np.pi * tod / 24)
    out["dow"] = t_ts.dayofweek.to_numpy().astype(float)
    out["in_window"] = ((tod >= s.window[0]) & (tod < s.window[1])).astype(float)

    # weather as known at the origin
    temp_fc = np.empty(len(tgt))
    ghi_fc = np.empty(len(tgt))
    wx_fc = np.empty(len(tgt))
    for op in origins:
        m = o == op
        temp_fc[m], ghi_fc[m], wx_fc[m] = _weather_at(s, int(op), tgt[m], weather_source)
    out["temp_fc"] = temp_fc
    out["ghi_fc"] = ghi_fc
    out["wx_forecast"] = wx_fc
    out["pv_proxy_fc"] = ghi_fc * s.pv_ratio
    out["temp_delta"] = temp_fc - anchor_mean(s.temp)
    out["ghi_delta"] = ghi_fc - anchor_mean(s.ghi)
    out["temp_origin"] = s.temp[o]

    df = pd.DataFrame(out)
    df["mp_id"] = s.mp_id
    df["origin_ts"] = s.ts(o)
    df["target_ts"] = t_ts
    df["target_date"] = t_dates
    if with_target:
        df["y"] = net[tgt]
        df["gross"] = gross[tgt]
        df["gen"] = gen[tgt]
    return df


def hourly(s: Series, end: int) -> pd.DataFrame:
    """Hourly means of net load and measured weather over positions [0, end] (whole hours only), with workday flags."""
    pos = np.arange(0, end + 1)
    t = s.ts(pos)
    df = pd.DataFrame({"net": s.net[pos], "temp": s.temp[pos], "ghi": s.ghi[pos]}, index=t)
    h = df.resample("h").mean()
    counts = df["net"].resample("h").count()
    h = h[counts >= PER_HOUR]
    wd, _ = s.day_info(np.array(h.index.date))
    h["workday"] = wd.astype(float)
    return h


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None

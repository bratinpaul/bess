"""Windows and their feature vectors.

A window is (system, start, end). Its features come in four families:
    telemetry   per signal: mean, max, min, std, slope (/h), last, change over the window (+ staleness, SOC drift at rest)
    signature   every fault_signature condition evaluated on the window (soft match 0..1, NaN = signal not available)
                and each fault's weighted signature score - the domain knowledge that makes 70 episodes usable
    alarm       count of each alarm_code in the window, total, distinct and max severity
    context     hour of day (sin / cos), share of charging / discharging / idle intervals, mean SOC and ambient

Leakage modes (how an episode's window is cut):
    triage  [detected − lookback, detected + post]; the defining alarm is in the window (alarm triage / correlation)
    early   [detected − lookback, detected); the defining alarm is never seen - telemetry and precursors only
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from usecases.fault_diag import data as D

STATS = ("mean", "max", "min", "std", "slope", "last", "roc")
FAMILIES = {"telemetry": "Telemetry window statistics", "signature": "Signature matches",
            "alarm": "Alarms in the window", "context": "Operating context"}


@dataclass
class Window:
    key: str                      # unique id of the example
    group: str                    # CV group (episode id, or the healthy anchor)
    system_id: int                # telemetry system
    start: pd.Timestamp
    end: pd.Timestamp
    label: Optional[str] = None   # fault_code (None for scans)
    episode_id: Optional[str] = None
    weight: float = 1.0
    kind: str = "episode"         # episode | none | scan
    exclude_alarms: set = field(default_factory=set)   # alarm ids hidden from this window (early mode)


class FrameIndex:
    """A telemetry frame as numpy arrays with a time index for fast window slicing."""

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.t = frame["ts"].values.astype("datetime64[ns]").astype(np.int64) if not frame.empty else np.array([], np.int64)
        cols = [c for c in D.SIGNALS if c in frame.columns]
        self.cols = cols
        self.values = frame[cols].to_numpy(dtype=float) if not frame.empty else np.empty((0, len(cols)))
        self.col_ix = {c: i for i, c in enumerate(cols)}
        self.present = frame["ems_rows"].notna().to_numpy() if "ems_rows" in frame else np.ones(len(frame), bool)
        mode = frame["mode_code"].fillna("").astype(str).str.lower() if "mode_code" in frame else pd.Series([], dtype=str)
        cur = frame["pack_current_a"].to_numpy(dtype=float) if "pack_current_a" in frame else np.zeros(len(frame))
        self.charging = (mode.str.contains("charg") & ~mode.str.contains("discharg")).to_numpy() | (cur < -1)
        self.discharging = mode.str.contains("discharg").to_numpy() | (cur > 1)
        self.idle = np.abs(np.nan_to_num(cur)) < 1.0
        self.soc = frame["soc_pct"].to_numpy(dtype=float) if "soc_pct" in frame else np.full(len(frame), np.nan)
        # which signature signals this frame can produce at all
        self.available = {c for c in cols if np.isfinite(self.values[:, self.col_ix[c]]).any()}
        self.available |= set(D.WINDOW_SIGNALS)

    def span(self, start: pd.Timestamp, end: pd.Timestamp, inclusive_end: bool = True) -> slice:
        a = np.searchsorted(self.t, start.value, side="left")
        b = np.searchsorted(self.t, end.value, side="right" if inclusive_end else "left")
        return slice(a, b)

    @property
    def t0(self):
        return pd.Timestamp(self.t[0], tz="UTC").tz_convert(D.TZ) if len(self.t) else None

    @property
    def t1(self):
        return pd.Timestamp(self.t[-1], tz="UTC").tz_convert(D.TZ) if len(self.t) else None


def _slope_per_h(t: np.ndarray, y: np.ndarray) -> float:
    ok = np.isfinite(y)
    if ok.sum() < 3:
        return np.nan
    x = (t[ok] - t[ok][0]) / 3.6e12
    if np.ptp(x) == 0:
        return np.nan
    return float(np.polyfit(x, y[ok], 1)[0])


def _stats(t: np.ndarray, y: np.ndarray) -> dict:
    ok = np.isfinite(y)
    if not ok.any():
        return {s: np.nan for s in STATS}
    yy = y[ok]
    return {"mean": float(yy.mean()), "max": float(yy.max()), "min": float(yy.min()),
            "std": float(yy.std()) if len(yy) > 1 else 0.0, "slope": _slope_per_h(t, y), "last": float(yy[-1]),
            "roc": float(yy[-1] - yy[0])}


def window_signals(fx: FrameIndex, sl: slice) -> dict:
    """Window-level signals: staleness (longest run of missing EMS buckets) and SOC drift at rest (%/day)."""
    pres = fx.present[sl]
    longest = run = 0
    for p in pres:
        run = 0 if p else run + 1
        longest = max(longest, run)
    if len(pres) == 0:
        longest = 1
    idle = fx.idle[sl] & np.isfinite(fx.soc[sl])
    drift = np.nan
    if idle.sum() >= 4:
        t = fx.t[sl][idle]
        slope_h = _slope_per_h(t, fx.soc[sl][idle])
        drift = -slope_h * 24 if np.isfinite(slope_h) else np.nan
    return {"telemetry_staleness_s": float(longest * 300), "self_discharge_pct_day": drift}


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def match_signatures(sigs: pd.DataFrame, fx: FrameIndex, w: Window, al: pd.DataFrame, soft_pct: float,
                     wsig: dict) -> list[dict]:
    """Every signature evaluated on the window: soft match m in [0, 1] (None when the signal isn't available), the value
    it saw and why."""
    out = []
    codes_in = set(al["alarm_code"].dropna()) if not al.empty else set()
    width = max((w.end - w.start).total_seconds() / 60, 5)
    for s in sigs.itertuples(index=False):
        kind, op, sig = (s.signal_kind or "TELEMETRY"), (s.operator or ">"), s.signal
        m, value = None, None
        if kind == "ALARM" or op == "PRESENT":
            m = 1.0 if sig in codes_in else 0.0
            value = int(sig in codes_in)
        elif sig in D.UNAVAILABLE:
            m = None
        else:
            tail = pd.Timedelta(minutes=min(float(s.window_min or width), width))
            if sig in wsig:
                x_series = np.array([wsig[sig]])
            elif sig in fx.col_ix:
                sl = fx.span(max(w.start, w.end - tail), w.end)
                x_series = fx.values[sl, fx.col_ix[sig]]
            else:
                x_series = np.array([])
            ok = x_series[np.isfinite(x_series)] if len(x_series) else x_series
            if len(ok):
                thr = s.threshold if s.threshold is not None and np.isfinite(s.threshold) else 0.0
                scale = max(abs(thr) * soft_pct, 1e-3)
                if op in (">", ">="):
                    value = float(ok.max())
                    m = float(_sigmoid((value - thr) / scale))
                elif op in ("<", "<="):
                    value = float(ok.min())
                    m = float(_sigmoid((thr - value) / scale))
                elif op == "==":
                    value = float(ok[-1])
                    m = float(np.isclose(value, thr))
                elif op == "!=":
                    value = float(ok[-1])
                    m = float(not np.isclose(value, thr))
                elif op in ("RISING", "FALLING") and len(ok) >= 3:
                    slope = float(np.polyfit(np.arange(len(ok)), ok, 1)[0])
                    value = slope
                    sd = float(ok.std()) or 1.0
                    m = float(_sigmoid((slope if op == "RISING" else -slope) * len(ok) / sd))
        out.append({"signature_id": int(s.signature_id), "fault_code": s.fault_code, "signal": sig, "kind": kind,
                    "operator": op, "threshold": D._num(s.threshold), "unit": s.unit, "weight": float(s.weight),
                    "value": value, "match": m})
    return out


def build_vector(fx: FrameIndex, w: Window, al_all: pd.DataFrame, sigs: pd.DataFrame, codes: list[str],
                 soft_pct: float) -> tuple[dict, list[dict]]:
    """One window -> (feature dict, signature evidence)."""
    sl = fx.span(w.start, w.end)
    t = fx.t[sl]
    feats: dict[str, float] = {}
    for c in fx.cols:
        st = _stats(t, fx.values[sl, fx.col_ix[c]])
        for k, v in st.items():
            feats[f"tel__{c}__{k}"] = v
    wsig = window_signals(fx, sl)
    for k, v in wsig.items():
        feats[f"tel__{k}"] = v
    # alarms in the window (minus the hidden ones)
    if al_all.empty:
        al = al_all
    else:
        al = al_all[(al_all["time"] >= w.start) & (al_all["time"] <= w.end)]
        if w.exclude_alarms:
            al = al[~al["alarm_id"].isin(w.exclude_alarms)]
    counts = al["alarm_code"].value_counts() if not al.empty else pd.Series(dtype=int)
    for c in codes:
        feats[f"alarm__{c}"] = float(counts.get(c, 0))
    feats["alarm__count"] = float(len(al))
    feats["alarm__distinct"] = float(al["alarm_code"].nunique()) if not al.empty else 0.0
    feats["alarm__max_severity"] = float(al["severity_level"].max()) if not al.empty else 0.0
    # context
    hour = w.end.hour + w.end.minute / 60
    feats["ctx__hour_sin"] = float(np.sin(2 * np.pi * hour / 24))
    feats["ctx__hour_cos"] = float(np.cos(2 * np.pi * hour / 24))
    n = max(sl.stop - sl.start, 1)
    feats["ctx__share_charging"] = float(fx.charging[sl].sum() / n)
    feats["ctx__share_discharging"] = float(fx.discharging[sl].sum() / n)
    feats["ctx__share_idle"] = float(fx.idle[sl].sum() / n)
    # signatures
    ev = match_signatures(sigs, fx, w, al, soft_pct, wsig)
    by_fault: dict[str, list] = {}
    for e in ev:
        feats[f"sig__{e['signature_id']}"] = np.nan if e["match"] is None else e["match"]
        if e["match"] is not None:
            by_fault.setdefault(e["fault_code"], []).append((e["weight"], e["match"]))
    for fc in sigs["fault_code"].unique():
        items = by_fault.get(fc, [])
        feats[f"sigscore__{fc}"] = (sum(a * b for a, b in items) / sum(a for a, _ in items)) if items else np.nan
    return feats, ev


def family_of(col: str) -> str:
    if col.startswith("tel__"):
        return "telemetry"
    if col.startswith(("sig__", "sigscore__")):
        return "signature"
    if col.startswith("alarm__"):
        return "alarm"
    return "context"


def feature_label(col: str, sig_lookup: dict) -> str:
    """Readable name for a feature column (shown in the diagnosis panel)."""
    if col.startswith("tel__"):
        parts = col.split("__")
        sig = parts[1]
        lab = (D.SIGNALS.get(sig) or D.WINDOW_SIGNALS.get(sig) or (sig,))[0]
        return f"{lab} ({parts[2]})" if len(parts) > 2 else lab
    if col.startswith("sigscore__"):
        return f"signature score {col.split('__', 1)[1]}"
    if col.startswith("sig__"):
        s = sig_lookup.get(int(col.split("__")[1]))
        if s:
            thr = "" if s["threshold"] is None else f" {s['threshold']:g}"
            return f"{s['signal']} {s['operator']}{thr} → {s['fault_code']}"
        return col
    if col.startswith("alarm__"):
        k = col.split("__", 1)[1]
        return {"count": "alarm count", "distinct": "distinct alarms", "max_severity": "max alarm severity"}.get(k, f"alarm {k}")
    return {"ctx__hour_sin": "hour of day (sin)", "ctx__hour_cos": "hour of day (cos)",
            "ctx__share_charging": "share charging", "ctx__share_discharging": "share discharging",
            "ctx__share_idle": "share idle"}.get(col, col)

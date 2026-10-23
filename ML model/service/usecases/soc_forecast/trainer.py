"""SOC trajectory forecasting: one run = physics fit per EMS, residual models per plan source, backtest, scores.

Methods (each a P10 / P50 / P90 trajectory, 5-min steps, `horizon` hours ahead):
  hold                naïve: SOC stays where it is (the bar to beat)
  physics_typical     coulomb counting on the typical-day setpoint profile; band = training residual quantiles
  physics_scheduled   coulomb counting on the dispatch schedule (dispatch_event), typical day where no command
  hybrid_typical      physics_typical + LightGBM quantile models on its residual
  hybrid_scheduled    physics_scheduled + LightGBM quantile models on its residual
The scheduled methods assume the dispatch commands were known at the origin (as with a day-ahead schedule); the
typical ones need no schedule - the gap between them is what a schedule is worth.

Residual features (known at the origin): steps ahead, SOC now and its rate of change (15 / 60 min), the setpoint,
mode, grid service, AGC, aux and HVAC load now, target SOC, the physics SOC and its change, planned charge / discharge
energy up to the step, the planned power at the step, whether physics sits on a limit, schedule coverage, target and
origin hour, EMS.

Scores on the test period: MAE / RMSE (SOC points), MAE at 1 h / 4 h / end, max error, P10-P90 coverage and width,
skill vs hold, drawdown error (min SOC over the horizon, P50 vs actual) and worst-case breach (actual min below the
P10 min - what the optimizer plans against).
"""
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from core.base import UseCaseError
from core.metrics import finite, shares
from usecases.soc_forecast import features as F

METHODS = ["hold", "physics_typical", "physics_scheduled", "hybrid_typical", "hybrid_scheduled"]
PLAN_SOURCES = ["typical", "scheduled"]
QUANTILES = (0.1, 0.5, 0.9)
RESIDUAL_FEATURES = ["h_min", "soc0", "dsoc_15", "dsoc_60", "sp0", "mode0", "gs0", "agc0", "aux0", "hvac0",
                     "target_soc0", "phys", "phys_delta", "e_chg_kwh", "e_dis_kwh", "plan_kw", "at_limit",
                     "sched_cov", "hour_t", "hour_o", "ems_code"]
GBM_PARAMS = [
    {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 20, "max": 5000, "step": 10},
    {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
    {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 31, "min": 2, "max": 512, "step": 1},
    {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 200, "min": 5, "max": 20000, "step": 5},
    {"name": "subsample", "label": "Row subsample", "type": "float", "default": 0.8, "min": 0.1, "max": 1, "step": 0.05},
    {"name": "colsample_bytree", "label": "Feature subsample", "type": "float", "default": 0.9, "min": 0.1, "max": 1, "step": 0.05},
]


class SocForecastError(UseCaseError):
    """Bad training / forecast input (the API answers 400)."""
    code = "SOC_FORECAST_INPUT_REJECTED"


@dataclass
class RunConfig:
    selection: F.Selection
    horizon_h: float = 12.0
    test_fraction: float = 0.2
    origin_step_min: int = 60
    train_origin_step_min: int = 60
    train_horizon_step: int = 3  # every n-th 5-min step of the horizon in the training rows
    soc_limits: Optional[tuple[float, float]] = None
    gbm_params: dict = field(default_factory=dict)
    store_every_n_origins: int = 6
    seed: int = 42


@dataclass
class Unit:
    ems_id: int
    df: pd.DataFrame
    physics: F.Physics
    typical: np.ndarray
    sched_sp: np.ndarray  # scheduled setpoint per series timestamp (NaN = no command)
    cut: int  # first test position
    sched_future: Optional[np.ndarray] = None  # live: scheduled setpoint per future step


def clean_gbm(params: dict) -> dict:
    out = {}
    for s in GBM_PARAMS:
        v = params.get(s["name"], s["default"])
        v = s["default"] if v in (None, "") else v
        v = int(v) if s["type"] == "int" else float(v)
        if not s["min"] <= v <= s["max"]:
            raise SocForecastError(f"{s['label']} must be between {s['min']} and {s['max']}")
        out[s["name"]] = v
    return out


# ---------------------------------------------------------------- plans and rows


def valid_origins(ok: np.ndarray, lo: int, hi: int, H: int, step: int) -> np.ndarray:
    """Positions o in [lo, hi) with gap-free history (1 h) and horizon (H steps)."""
    bad = np.concatenate([[0], np.cumsum(~ok)])
    o = np.arange(max(lo, F.HISTORY_STEPS), min(hi, len(ok) - H - 1) + 1, step)
    if not len(o):
        return o
    return o[(bad[o + H + 1] - bad[o - F.HISTORY_STEPS]) == 0]


def plans(u: Unit, origins: np.ndarray, H: int, ts_future=None) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Plan matrices (n, H) per source and the schedule coverage per step (scheduled only)."""
    idx = origins[:, None] + np.arange(H)[None, :]
    if ts_future is None:
        ts = u.df.index
        slots = F.slot_of(ts)[np.minimum(idx, len(ts) - 1)]
        sched = u.sched_sp[np.minimum(idx, len(ts) - 1)]
    else:  # live: the steps are beyond the series
        slots = F.slot_of(ts_future)[None, :].repeat(len(origins), axis=0)
        sched = u.sched_future[None, :].repeat(len(origins), axis=0)
    typical = u.typical[slots]
    sp_now = u.df["sp"].to_numpy()[origins]
    typ = typical.copy()
    typ[:, 0] = sp_now  # the current command is known
    sch = np.where(np.isnan(sched), typical, sched)
    sch[:, 0] = np.where(np.isnan(sched[:, 0]), sp_now, sched[:, 0])
    return {"typical": (typ, np.zeros_like(typ)), "scheduled": (sch, (~np.isnan(sched)).astype(float))}


def residual_rows(u: Unit, origins: np.ndarray, H: int, source: str, steps: np.ndarray,
                  plan: np.ndarray, cover: np.ndarray, phys: np.ndarray, with_target: bool = True) -> pd.DataFrame:
    df = u.df
    soc = df["soc"].to_numpy()
    n = len(origins)
    k = np.tile(steps, n)
    o = np.repeat(origins, len(steps))
    r = np.repeat(np.arange(n), len(steps))
    e_chg = np.cumsum(np.clip(plan, 0, None), axis=1) * F.DT_H
    e_dis = np.cumsum(np.clip(-plan, 0, None), axis=1) * F.DT_H
    cov = np.cumsum(cover, axis=1) / np.arange(1, H + 1)[None, :]
    ph = u.physics
    origin_ts = df.index[o] if with_target else df.index[np.minimum(o, len(df) - 1)]
    out = pd.DataFrame({
        "h_min": (k + 1) * F.STEP_MIN,
        "soc0": soc[o],
        "dsoc_15": soc[o] - soc[o - 3],
        "dsoc_60": soc[o] - soc[o - 12],
        "sp0": df["sp"].to_numpy()[o],
        "mode0": pd.Categorical(df["mode"].to_numpy()[o], categories=F.MODES).codes.astype(float),
        "gs0": pd.Categorical(df["gs"].to_numpy()[o], categories=F.SERVICES).codes.astype(float),
        "agc0": df["agc"].to_numpy()[o],
        "aux0": df["aux_kw"].to_numpy()[o],
        "hvac0": df["hvac_kw"].to_numpy()[o],
        "target_soc0": df["target_soc"].to_numpy()[o],
        "phys": phys[r, k],
        "phys_delta": phys[r, k] - soc[o],
        "e_chg_kwh": e_chg[r, k],
        "e_dis_kwh": e_dis[r, k],
        "plan_kw": plan[r, k],
        "at_limit": ((phys[r, k] <= ph.soc_min + 1e-6) | (phys[r, k] >= ph.soc_max - 1e-6)).astype(float),
        "sched_cov": cov[r, k],
        "hour_t": ((origin_ts.hour.to_numpy() * 60 + origin_ts.minute.to_numpy() + (k + 1) * F.STEP_MIN) // 60) % 24,
        "hour_o": origin_ts.hour.to_numpy().astype(float),
        "ems_code": float(u.ems_id),
    })
    out["row"], out["step"], out["pos"] = r, k, o
    if with_target:
        out["y"] = soc[o + k + 1] - phys[r, k]
        out["actual"] = soc[o + k + 1]
    return out


# ---------------------------------------------------------------- residual model


class ResidualModel:
    def __init__(self, params: dict, seed: int):
        self.params = params
        self.seed = seed
        self.models: dict[float, Any] = {}

    def fit(self, rows: pd.DataFrame) -> "ResidualModel":
        X, y = rows[RESIDUAL_FEATURES], rows["y"].to_numpy()
        for q in QUANTILES:
            self.models[q] = lgb.LGBMRegressor(objective="quantile", alpha=q, random_state=self.seed, verbose=-1,
                                               n_jobs=4, subsample_freq=1, **self.params).fit(X, y)
        return self

    def predict(self, rows: pd.DataFrame) -> dict[float, np.ndarray]:
        X = rows[RESIDUAL_FEATURES]
        return {q: m.predict(X) for q, m in self.models.items()}

    def importance(self) -> dict[str, float]:
        b = self.models[0.5].booster_
        return shares(dict(zip(b.feature_name(), b.feature_importance(importance_type="gain").astype(float))))


def band_offsets(rows: pd.DataFrame, H: int) -> np.ndarray:
    """(H, 2) P10 / P90 offsets of the physics residual per step (pooled over neighbouring steps)."""
    out = np.zeros((H, 2))
    k = rows["step"].to_numpy()
    y = rows["y"].to_numpy()
    for s in range(H):
        m = np.abs(k - s) <= 3
        r = y[m] if m.sum() >= 30 else y
        out[s] = np.quantile(r, [0.1, 0.9]) if len(r) else 0.0
    return out


# ---------------------------------------------------------------- training


def load_units(engine: Engine, sel: F.Selection, cfg: RunConfig, warnings: list[str]) -> list[Unit]:
    H = int(round(cfg.horizon_h * 60 / F.STEP_MIN))
    units = []
    for ems in sel.ems_ids:
        df = F.series(engine, ems, sel.date_from, sel.date_to)
        if len(df) < H * 3:
            warnings.append(f"EMS {ems}: only {len(df)} readings - left out")
            continue
        if (~df["ok"]).sum():
            warnings.append(f"EMS {ems}: {int((~df['ok']).sum())} 5-min readings missing; origins touching a gap are skipped")
        cut = int(round(len(df) * (1 - cfg.test_fraction)))
        train = df.iloc[:cut]
        physics = F.fit_physics(train[train["ok"]] if train["ok"].any() else train, cfg.soc_limits)
        typical = F.typical_profile(train[train["ok"]])
        sched = F.schedule(engine, ems)
        sched_sp, _ = F.schedule_grid(sched, df.index)
        if sched.empty:
            warnings.append(f"EMS {ems}: no dispatch commands - the scheduled plan is the typical day")
        units.append(Unit(ems, df, physics, typical, sched_sp, cut))
    if not units:
        raise SocForecastError("No EMS with enough SOC history in the selection")
    return units


def train(engine: Engine, cfg: RunConfig) -> tuple[dict, dict, pd.DataFrame, list[str]]:
    """Returns (artifact, summary, stored backtest points, warnings)."""
    started = time.perf_counter()
    warnings: list[str] = []
    H = int(round(cfg.horizon_h * 60 / F.STEP_MIN))
    gbm = clean_gbm(cfg.gbm_params)
    units = load_units(engine, cfg.selection, cfg, warnings)
    tr_steps = np.arange(0, H, max(1, cfg.train_horizon_step))
    all_steps = np.arange(H)

    train_rows = {s: [] for s in PLAN_SOURCES}
    test_parts = []
    for u in units:
        ok = u.df["ok"].to_numpy()
        tr_o = valid_origins(ok, 0, u.cut - H - 1, H, max(1, cfg.train_origin_step_min // F.STEP_MIN))
        te_o = valid_origins(ok, u.cut, len(ok), H, max(1, cfg.origin_step_min // F.STEP_MIN))
        if len(tr_o) < 20 or not len(te_o):
            warnings.append(f"EMS {u.ems_id}: too few gap-free origins for a {cfg.horizon_h:g} h horizon - left out")
            continue
        soc = u.df["soc"].to_numpy()
        for o_set, target in ((tr_o, "train"), (te_o, "test")):
            pl = plans(u, o_set, H)
            for src in PLAN_SOURCES:
                plan, cov = pl[src]
                phys = u.physics.roll(soc[o_set], plan)
                rows = residual_rows(u, o_set, H, src, tr_steps if target == "train" else all_steps, plan, cov, phys)
                if target == "train":
                    train_rows[src].append(rows)
                else:
                    rows["source"] = src
                    rows["ems_id"] = u.ems_id
                    test_parts.append(rows)
    if not test_parts:
        raise SocForecastError("No EMS has enough gap-free history for training and testing")

    models, offsets, importance, n_train = {}, {}, {}, 0
    for src in PLAN_SOURCES:
        rows = pd.concat(train_rows[src], ignore_index=True)
        n_train += len(rows)
        offsets[src] = band_offsets(rows, H)
        models[src] = ResidualModel(gbm, cfg.seed).fit(rows)
        importance[src] = models[src].importance()

    # backtest: every method on the same origins
    test = pd.concat(test_parts, ignore_index=True)
    limits = {u.ems_id: (u.physics.soc_min, u.physics.soc_max) for u in units}
    lo_lim = test["ems_id"].map(lambda e: limits[e][0]).to_numpy()
    hi_lim = test["ems_id"].map(lambda e: limits[e][1]).to_numpy()
    preds: dict[str, pd.DataFrame] = {}
    for src in PLAN_SOURCES:
        t = test[test["source"] == src].reset_index(drop=True)
        lo, hi = lo_lim[test["source"].to_numpy() == src], hi_lim[test["source"].to_numpy() == src]
        off = offsets[src][t["step"].to_numpy()]
        phys = t["phys"].to_numpy()
        preds[f"physics_{src}"] = _frame(t, np.clip(phys + off[:, 0], lo, hi), phys, np.clip(phys + off[:, 1], lo, hi))
        q = models[src].predict(t)
        preds[f"hybrid_{src}"] = _frame(t, np.clip(phys + q[0.1], lo, hi), np.clip(phys + q[0.5], lo, hi),
                                        np.clip(phys + q[0.9], lo, hi))
    t = test[test["source"] == "typical"].reset_index(drop=True)
    hold_off = band_offsets(pd.concat(train_rows["typical"]).assign(y=lambda r: r["y"] + r["phys_delta"]), H)
    s0 = t["soc0"].to_numpy()
    lo, hi = lo_lim[test["source"].to_numpy() == "typical"], hi_lim[test["source"].to_numpy() == "typical"]
    off = hold_off[t["step"].to_numpy()]
    preds["hold"] = _frame(t, np.clip(s0 + off[:, 0], lo, hi), s0, np.clip(s0 + off[:, 1], lo, hi))

    hold_mae = float(np.mean(np.abs(preds["hold"]["actual"] - preds["hold"]["p50"])))
    metrics, by_step = {}, {}
    for m in METHODS:
        p = preds[m]
        metrics[m] = score(p, hold_mae)
        err = np.abs(p["actual"] - p["p50"]).groupby(p["step"]).mean()
        by_step[m] = [finite(err.get(s, np.nan)) for s in range(0, H, 3)]
    best = min(metrics, key=lambda k: metrics[k]["mae"] if metrics[k]["mae"] is not None else 1e9)

    # stored points: every n-th origin per EMS, every method, all steps
    keep = []
    for ems, g in t.groupby("ems_id"):
        origins = np.sort(g["pos"].unique())[::max(1, cfg.store_every_n_origins)]
        keep.append(set(zip([ems] * len(origins), origins)))
    keep_set = set().union(*keep) if keep else set()
    pts = []
    for m in METHODS:
        p = preds[m]
        mask = np.array([(e, o) in keep_set for e, o in zip(p["ems_id"], p["pos"])])
        q = p[mask].copy()
        q["method"] = m
        pts.append(q)
    points = pd.concat(pts, ignore_index=True)
    unit_by_id = {u.ems_id: u for u in units}
    points["origin_ts"] = [unit_by_id[e].df.index[o] for e, o in zip(points["ems_id"], points["pos"])]

    artifact = {
        "horizon_steps": H, "models": models, "offsets": offsets, "hold_offsets": hold_off,
        "physics": {u.ems_id: u.physics for u in units}, "typical": {u.ems_id: u.typical for u in units},
        "ems_ids": [u.ems_id for u in units],
    }
    summary = {
        "n_train_rows": int(n_train), "n_test_origins": int(t.groupby(["ems_id", "pos"]).ngroups),
        "best_method": best, "metrics": metrics,
        "results": {
            "mae_by_step": by_step, "step_every_min": 15, "importance": importance,
            "physics": {str(u.ems_id): u.physics.to_dict() for u in units},
            "typical": {str(u.ems_id): [finite(v) for v in u.typical] for u in units},
            "split": {str(u.ems_id): {"test_from": u.df.index[u.cut].isoformat(), "to": u.df.index[-1].isoformat()}
                      for u in units},
            "schedule_coverage": {str(u.ems_id): finite(np.mean(~np.isnan(u.sched_sp[u.cut:]))) for u in units},
        },
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return artifact, summary, points, warnings


def _frame(t: pd.DataFrame, p10, p50, p90) -> pd.DataFrame:
    q = np.sort(np.vstack([p10, p50, p90]), axis=0)
    return pd.DataFrame({"ems_id": t["ems_id"].to_numpy(), "pos": t["pos"].to_numpy(), "step": t["step"].to_numpy(),
                         "row": t["row"].to_numpy(), "p10": q[0], "p50": q[1], "p90": q[2],
                         "actual": t["actual"].to_numpy(), "plan_kw": t["plan_kw"].to_numpy()})


def score(p: pd.DataFrame, hold_mae: float) -> dict:
    err = p["actual"].to_numpy() - p["p50"].to_numpy()
    step = p["step"].to_numpy()
    at = lambda s: finite(np.mean(np.abs(err[step == s]))) if (step == s).any() else None  # noqa: E731
    H = int(step.max()) + 1
    g = p.groupby(["ems_id", "pos"])
    mins = g.agg(actual_min=("actual", "min"), p50_min=("p50", "min"), p10_min=("p10", "min"))
    return {
        "n": int(len(p)), "mae": finite(np.mean(np.abs(err))), "rmse": finite(np.sqrt(np.mean(err ** 2))),
        "mae_1h": at(11), "mae_4h": at(min(47, H - 1)), "mae_end": at(H - 1),
        "max_error": finite(np.max(np.abs(err))),
        "coverage_pct": finite(100 * np.mean((p["actual"] >= p["p10"]) & (p["actual"] <= p["p90"]))),
        "width": finite(np.mean(p["p90"] - p["p10"])),
        "skill_pct": finite(100 * (1 - np.mean(np.abs(err)) / hold_mae)) if hold_mae else None,
        "drawdown_mae": finite(np.mean(np.abs(mins["p50_min"] - mins["actual_min"]))),
        "breach_pct": finite(100 * np.mean(mins["actual_min"] < mins["p10_min"] - 0.5)),
    }


# ---------------------------------------------------------------- live forecast


def forecast(engine: Engine, art: dict, ems_id: int, source: str, custom: Optional[list[dict]] = None,
             history_hours: int = 24, horizon_h: Optional[float] = None) -> dict:
    """Trajectories from the newest gap-free reading with every method, for a plan source (typical / scheduled /
    custom). Custom blocks: [{start, end, kw}] (ISO times) - steps outside them follow the typical day."""
    if ems_id not in art["ems_ids"]:
        raise SocForecastError(f"EMS {ems_id} is not part of this model (trained on EMS {', '.join(map(str, art['ems_ids']))})")
    H = art["horizon_steps"] if not horizon_h else min(art["horizon_steps"], int(round(horizon_h * 60 / F.STEP_MIN)))
    df = F.series(engine, ems_id, (pd.Timestamp.now(tz=F.TZ) - pd.Timedelta(days=400)).date())
    if df.empty:
        raise SocForecastError(f"EMS {ems_id} has no SOC readings")
    ok = df["ok"].to_numpy()
    last = int(np.flatnonzero(ok)[-1])
    if not ok[max(0, last - F.HISTORY_STEPS):last + 1].all():
        raise SocForecastError(f"EMS {ems_id}: the last hour of readings has gaps")
    df = df.iloc[:last + 1]
    phys_model: F.Physics = art["physics"][ems_id]
    origin_ts = df.index[-1]
    future = pd.date_range(origin_ts, periods=H, freq=f"{F.STEP_MIN}min", tz=F.TZ)  # step k governs [k, k+1)
    sched = F.schedule(engine, ems_id)
    sched_future, _ = F.schedule_grid(sched, future)
    u = Unit(ems_id, df, phys_model, art["typical"][ems_id], np.full(len(df), np.nan), len(df), sched_future)
    o = np.array([len(df) - 1])
    pl = plans(u, o, H, ts_future=future)
    if source == "custom":
        plan = pl["typical"][0].copy()
        cover = np.zeros_like(plan)
        t = future.asi8
        for b in custom or []:
            s, e = pd.Timestamp(b["start"]).value, pd.Timestamp(b["end"]).value
            m = (t >= s) & (t < e)
            plan[0, m] = float(b["kw"])
            cover[0, m] = 1.0
        src_model = "scheduled"
    else:
        plan, cover = pl[source]
        src_model = source
    soc0 = df["soc"].to_numpy()[o]
    phys = phys_model.roll(soc0, plan)
    rows = residual_rows(u, o, H, src_model, np.arange(H), plan, cover, phys, with_target=False)
    lo, hi = phys_model.soc_min, phys_model.soc_max
    steps = np.arange(H)
    q = art["models"][src_model].predict(rows)
    off = art["offsets"][src_model][steps]
    hold_off = art["hold_offsets"][steps]
    p = phys[0]
    traj = {
        "hold": _traj(np.clip(soc0[0] + hold_off[:, 0], lo, hi), np.full(H, soc0[0]), np.clip(soc0[0] + hold_off[:, 1], lo, hi)),
        "physics": _traj(np.clip(p + off[:, 0], lo, hi), p, np.clip(p + off[:, 1], lo, hi)),
        "hybrid": _traj(np.clip(p + q[0.1], lo, hi), np.clip(p + q[0.5], lo, hi), np.clip(p + q[0.9], lo, hi)),
    }
    ts_after = [t.isoformat() for t in future + pd.Timedelta(minutes=F.STEP_MIN)]
    hist = df.iloc[-history_hours * 12:]
    return {
        "ems_id": ems_id, "origin_ts": origin_ts.isoformat(), "soc_now": finite(soc0[0]), "source": source,
        "schedule_coverage": finite(cover.mean()), "physics": phys_model.to_dict(),
        "times": ts_after, "plan_kw": [finite(v) for v in plan[0]], "plan_from_schedule": [bool(v) for v in cover[0]],
        "trajectories": traj,
        "history": [{"ts": t.isoformat(), "soc": finite(s), "sp": finite(sp), "mode": m}
                    for t, s, sp, m in zip(hist.index, hist["soc"], hist["sp"], hist["mode"])],
        "commands": [{"start": r.start.isoformat(), "end": r["end"].isoformat(), "kw": finite(r.sp), "mode": r["mode"],
                      "source": r["source"]} for _, r in sched[sched["end"] > origin_ts - pd.Timedelta(hours=history_hours)].iterrows()]
        if not sched.empty else [],
        "derived": derived(traj, phys_model, ts_after),
    }


def _traj(p10, p50, p90) -> dict:
    q = np.sort(np.vstack([p10, p50, p90]), axis=0)
    return {"p10": [finite(v) for v in q[0]], "p50": [finite(v) for v in q[1]], "p90": [finite(v) for v in q[2]]}


def derived(traj: dict, ph: F.Physics, times: list[str]) -> dict:
    """Available discharge energy and charge headroom along the hybrid P50 (and worst case), time to the limits."""
    p50 = np.array(traj["hybrid"]["p50"], float)
    p10 = np.array(traj["hybrid"]["p10"], float)
    p90 = np.array(traj["hybrid"]["p90"], float)

    def first(mask):
        i = np.flatnonzero(mask)
        return times[i[0]] if len(i) else None

    return {
        "discharge_kwh_p50": [finite((s - ph.soc_min) / 100 * ph.cap_dis_kwh) for s in p50],
        "discharge_kwh_p10": [finite((s - ph.soc_min) / 100 * ph.cap_dis_kwh) for s in p10],
        "charge_headroom_kwh_p50": [finite((ph.soc_max - s) / 100 * ph.cap_chg_kwh) for s in p50],
        "time_to_min_p50": first(p50 <= ph.soc_min + 0.5), "time_to_min_p10": first(p10 <= ph.soc_min + 0.5),
        "time_to_max_p50": first(p50 >= ph.soc_max - 0.5), "time_to_max_p90": first(p90 >= ph.soc_max - 0.5),
        "min_soc_p10": finite(p10.min()), "min_soc_p50": finite(p50.min()), "max_soc_p90": finite(p90.max()),
    }

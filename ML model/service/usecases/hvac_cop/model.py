"""HVAC COP & cooling performance: data, measured COP three ways, and the performance models.

Measured (per interval):
  COP_logged = cop (the unit's own reading)        COP_ratio = cooling_capacity_kw / hvac_power_kw
  Q_loop     = flow_lpm/60 · ρ · cp · ΔT           COP_loop  = Q_loop / hvac_power_kw  (independent first-law check)
  condenser closure = heat_rejected_kw - (cooling_capacity_kw + hvac_power_kw)

Thermodynamic drivers:
  T_evap = coolant_supply - evap approach, T_cond = ambient + condenser approach (or the refrigerant pressures through an
  approximate R-410A saturation curve); lift = T_cond - T_evap; COP_carnot = T_evap / lift (K);
  PLR = compressor_speed_pct / 100.

Models (fitted on the steady-state training intervals):
  map     COP = biquad(T_evap, T_cond) · f_PLR(PLR)   CAP = biquad(T_evap, T_cond) · g(PLR)   (DOE-2 / ASHRAE style)
  grey    η_2nd = e0 + e1·PLR + e2·PLR² + e3·lift;  COP = η_2nd · COP_carnot
  hybrid  map + LightGBM on the map residual (ambient, supply, setpoint, speed, fan, pressures, humidity, flow, filter)
Power follows from CAP / COP.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

TZ = "Asia/Kolkata"
STEP_H = 5 / 60


class HvacCopError(Exception):
    """Bad input for a COP run (the API answers 400)."""


@dataclass
class ModelSettings:
    cop_definition: str = "logged"          # logged | ratio | loop
    capacity_definition: str = "logged"     # logged (cooling_capacity_kw) | loop (flow x dT)
    lift_source: str = "temperature"        # temperature | pressure
    evap_approach_k: float = 5.0
    cond_approach_k: float = 10.0
    fluid_density_kg_l: float = 1.04        # 30 % glycol
    fluid_cp_kj_kgk: float = 3.7
    min_speed_pct: float = 20.0
    min_power_kw: float = 1.0
    max_dt_step_k: float = 0.5              # |ΔT change| per interval for "steady"
    train_frac: float = 0.7
    expected_model: str = "map"             # map | grey | hybrid - the monitoring baseline
    n_estimators: int = 300
    learning_rate: float = 0.05
    num_leaves: int = 15


def units(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT u.hvac_id, u.hvac_code, u.battery_system_id, b.system_name, s.site_name, s.site_id,
                   u.cooling_capacity_kw, u.model, t.first_ts, t.last_ts, t.n, t.cooling
            FROM battery_master.hvac_unit u
            LEFT JOIN battery_master.battery_system b ON b.battery_system_id = u.battery_system_id
            LEFT JOIN battery_master.site s ON s.site_id = b.site_id
            JOIN LATERAL (SELECT min(ts) AS first_ts, max(ts) AS last_ts, count(*) AS n,
                                 count(*) FILTER (WHERE cooling_mode = 'COOLING') AS cooling
                          FROM battery_telemetry.hvac_telemetry WHERE hvac_id = u.hvac_id) t ON t.n > 0
            ORDER BY s.site_name, u.hvac_code""")).mappings().all()
    return [{"hvac_id": r["hvac_id"], "hvac_code": r["hvac_code"], "system_id": r["battery_system_id"],
             "system_name": r["system_name"], "site_name": r["site_name"], "site_id": r["site_id"],
             "rated_kw": float(r["cooling_capacity_kw"]) if r["cooling_capacity_kw"] is not None else None,
             "model": r["model"], "intervals": int(r["n"]), "cooling_intervals": int(r["cooling"]),
             "first_day": pd.Timestamp(r["first_ts"]).tz_convert(TZ).date().isoformat(),
             "last_day": pd.Timestamp(r["last_ts"]).tz_convert(TZ).date().isoformat()} for r in rows]


NUM = ["ambient_temp_c", "coolant_setpoint_c", "coolant_supply_temp_c", "coolant_return_temp_c", "coolant_delta_t_c",
       "coolant_flow_lpm", "compressor_speed_pct", "condenser_fan_pct", "refrig_suction_bar", "refrig_discharge_bar",
       "battery_heat_load_kw", "cooling_capacity_kw", "heat_rejected_kw", "hvac_power_kw", "cop", "enclosure_temp_c",
       "enclosure_humidity_pct", "filter_dp_pa", "cum_energy_kwh", "compressor_runtime_h", "units_running"]


def series(engine: Engine, hvac_id: int, d0: date, d1: date) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(text("""SELECT ts, cooling_mode, """ + ", ".join(NUM) + """ FROM battery_telemetry.hvac_telemetry
                                 WHERE hvac_id = :h AND ts >= CAST(:a AS date) AND ts < CAST(:b AS date) + 1 ORDER BY ts"""),
                         conn, params={"h": hvac_id, "a": d0, "b": d1})
    for c in NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    return df.reset_index(drop=True)


def r410a_tsat(p_bar: np.ndarray) -> np.ndarray:
    """Approximate R-410A saturation temperature (°C) from pressure (bar abs): T = -75.1 + 36.1·ln P."""
    return -75.1 + 36.1 * np.log(np.clip(p_bar, 0.5, None))


def derive(df: pd.DataFrame, cfg: ModelSettings) -> pd.DataFrame:
    df = df.copy()
    p = df["hvac_power_kw"]
    df["q_loop_kw"] = df["coolant_flow_lpm"] / 60 * cfg.fluid_density_kg_l * cfg.fluid_cp_kj_kgk * df["coolant_delta_t_c"]
    with np.errstate(divide="ignore", invalid="ignore"):
        df["cop_ratio"] = np.where(p > cfg.min_power_kw, df["cooling_capacity_kw"] / p, np.nan)
        df["cop_loop"] = np.where(p > cfg.min_power_kw, df["q_loop_kw"] / p, np.nan)
    df["cop_logged"] = df["cop"]
    df["cop_actual"] = {"logged": df["cop_logged"], "ratio": df["cop_ratio"], "loop": df["cop_loop"]}[cfg.cop_definition]
    df["cap_actual_kw"] = df["q_loop_kw"] if cfg.capacity_definition == "loop" else df["cooling_capacity_kw"]
    df["rej_closure_kw"] = df["heat_rejected_kw"] - (df["cooling_capacity_kw"] + p)
    if cfg.lift_source == "pressure":
        df["t_evap_c"] = r410a_tsat(df["refrig_suction_bar"].to_numpy())
        df["t_cond_c"] = r410a_tsat(df["refrig_discharge_bar"].to_numpy())
    else:
        df["t_evap_c"] = df["coolant_supply_temp_c"] - cfg.evap_approach_k
        df["t_cond_c"] = df["ambient_temp_c"] + cfg.cond_approach_k
    df["lift_k"] = df["t_cond_c"] - df["t_evap_c"]
    df["cop_carnot"] = np.where(df["lift_k"] > 1, (df["t_evap_c"] + 273.15) / df["lift_k"], np.nan)
    df["plr"] = df["compressor_speed_pct"] / 100
    with np.errstate(divide="ignore", invalid="ignore"):
        df["eta_2nd_law"] = df["cop_actual"] / df["cop_carnot"]
    cooling = df["cooling_mode"] == "COOLING"
    prev_cooling = cooling.shift(1, fill_value=False)
    stable_dt = df["coolant_delta_t_c"].diff().abs() <= cfg.max_dt_step_k
    df["steady"] = (cooling & prev_cooling & stable_dt & (df["compressor_speed_pct"] >= cfg.min_speed_pct)
                    & (p > cfg.min_power_kw) & df["cop_actual"].notna() & np.isfinite(df["cop_carnot"]))
    n_train = int(len(df) * cfg.train_frac)
    df["is_train"] = np.arange(len(df)) < n_train
    return df


# ---------------------------------------------------------------- performance maps


def _biquad_X(te: np.ndarray, tc: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(te)), te, te ** 2, tc, tc ** 2, te * tc])


def _lstsq(X: np.ndarray, y: np.ndarray, ridge: float = 1e-6) -> np.ndarray:
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X, y = X[ok], y[ok]
    if len(y) < X.shape[1] + 2:
        return np.zeros(X.shape[1])
    return np.linalg.solve(X.T @ X + ridge * np.eye(X.shape[1]), X.T @ y)


def fit_map(te: np.ndarray, tc: np.ndarray, plr: np.ndarray, y: np.ndarray, plr_order: int = 2, iters: int = 4) -> dict:
    """y = biquad(te, tc) · f(plr), f normalised to 1 at PLR = 1, by alternating least squares."""
    f = np.ones(len(y))
    b = np.zeros(6)
    p = np.array([1.0] + [0.0] * plr_order)
    for _ in range(iters):
        b = _lstsq(_biquad_X(te, tc), y / np.where(np.abs(f) > 1e-6, f, 1.0))
        base = _biquad_X(te, tc) @ b
        P = np.column_stack([plr ** k for k in range(plr_order + 1)])
        p = _lstsq(P, y / np.where(np.abs(base) > 1e-6, base, np.nan))
        norm = float(np.sum(p))  # f(1)
        if abs(norm) > 1e-6:
            p, b = p / norm, b * norm
        f = P @ p
    return {"biquad": b.tolist(), "plr": p.tolist()}


def eval_map(m: dict, te, tc, plr) -> np.ndarray:
    te, tc, plr = (np.atleast_1d(np.asarray(x, dtype=float)) for x in (te, tc, plr))
    base = _biquad_X(te, tc) @ np.array(m["biquad"])
    f = np.column_stack([plr ** k for k in range(len(m["plr"]))]) @ np.array(m["plr"])
    return base * f


def fit_grey(df: pd.DataFrame) -> dict:
    X = np.column_stack([np.ones(len(df)), df["plr"], df["plr"] ** 2, df["lift_k"]])
    c = _lstsq(X, df["eta_2nd_law"].to_numpy())
    return {"coef": c.tolist()}


def eval_grey(g: dict, plr, lift, carnot) -> np.ndarray:
    plr, lift, carnot = (np.atleast_1d(np.asarray(x, dtype=float)) for x in (plr, lift, carnot))
    eta = np.column_stack([np.ones(len(plr)), plr, plr ** 2, lift]) @ np.array(g["coef"])
    return eta * carnot


GBM_FEATURES = ["ambient_temp_c", "coolant_supply_temp_c", "coolant_setpoint_c", "compressor_speed_pct",
                "condenser_fan_pct", "refrig_suction_bar", "refrig_discharge_bar", "enclosure_humidity_pct",
                "coolant_flow_lpm", "filter_dp_pa", "lift_k"]


def scores(y: np.ndarray, p: np.ndarray) -> dict:
    ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() < 3:
        return {"n": int(ok.sum())}
    y, p = y[ok], p[ok]
    var = float(np.var(y))
    return {"n": int(len(y)), "r2": 1 - float(np.mean((y - p) ** 2)) / var if var > 0 else None,
            "mae": float(np.mean(np.abs(y - p))), "rmse": float(np.sqrt(np.mean((y - p) ** 2))),
            "mape_pct": float(100 * np.mean(np.abs((y - p) / np.where(np.abs(y) > 1e-9, y, np.nan)))),
            "bias": float(np.mean(p - y))}


def fit_models(df: pd.DataFrame, cfg: ModelSettings) -> tuple[dict, dict]:
    """Fit map / grey / hybrid COP and the capacity map on the steady training rows; write the predictions into df."""
    tr = df["steady"] & df["is_train"]
    te_ = df["steady"] & ~df["is_train"]
    if tr.sum() < 50:
        raise HvacCopError("Fewer than 50 steady-state training intervals - widen the window or relax the steady filter")
    g = df[tr]
    cop_map = fit_map(g["t_evap_c"].to_numpy(), g["t_cond_c"].to_numpy(), g["plr"].to_numpy(), g["cop_actual"].to_numpy())
    cap_map = fit_map(g["t_evap_c"].to_numpy(), g["t_cond_c"].to_numpy(), g["plr"].to_numpy(), g["cap_actual_kw"].to_numpy(),
                      plr_order=1)
    grey = fit_grey(g)
    df["cop_map"] = eval_map(cop_map, df["t_evap_c"], df["t_cond_c"], df["plr"])
    df["cop_grey"] = eval_grey(grey, df["plr"], df["lift_k"], df["cop_carnot"])
    df["cap_expected_kw"] = eval_map(cap_map, df["t_evap_c"], df["t_cond_c"], df["plr"])
    resid = (g["cop_actual"] - df.loc[tr, "cop_map"]).to_numpy()
    gbm = lgb.LGBMRegressor(n_estimators=cfg.n_estimators, learning_rate=cfg.learning_rate, num_leaves=cfg.num_leaves,
                            min_child_samples=20, subsample=0.9, subsample_freq=1, colsample_bytree=0.9,
                            random_state=42, verbose=-1, n_jobs=4)
    gbm.fit(g[GBM_FEATURES], resid)
    df["cop_hybrid"] = df["cop_map"] + gbm.predict(df[GBM_FEATURES])
    exp_col = {"map": "cop_map", "grey": "cop_grey", "hybrid": "cop_hybrid"}[cfg.expected_model]
    df["cop_expected"] = df[exp_col]
    df["cop_residual"] = df["cop_actual"] - df["cop_expected"]
    with np.errstate(divide="ignore", invalid="ignore"):
        df["power_expected_kw"] = df["cap_expected_kw"] / df["cop_expected"]
    df.loc[~(df["cooling_mode"] == "COOLING"), ["cop_map", "cop_grey", "cop_hybrid", "cop_expected", "cop_residual",
                                                 "cap_expected_kw", "power_expected_kw"]] = np.nan
    imp = gbm.booster_.feature_importance(importance_type="gain")
    tot = float(imp.sum()) or 1.0
    y_te = df.loc[te_, "cop_actual"].to_numpy()
    sc = {name: {"train": scores(g["cop_actual"].to_numpy(), df.loc[tr, col].to_numpy()),
                 "test": scores(y_te, df.loc[te_, col].to_numpy())}
          for name, col in (("map", "cop_map"), ("grey", "cop_grey"), ("hybrid", "cop_hybrid"))}
    sc["constant"] = {"test": scores(y_te, np.full(len(y_te), float(g["cop_actual"].median())))}
    sc["capacity_map"] = {"train": scores(g["cap_actual_kw"].to_numpy(), df.loc[tr, "cap_expected_kw"].to_numpy()),
                          "test": scores(df.loc[te_, "cap_actual_kw"].to_numpy(), df.loc[te_, "cap_expected_kw"].to_numpy())}
    sc["power"] = {"test": scores(df.loc[te_, "hvac_power_kw"].to_numpy(), df.loc[te_, "power_expected_kw"].to_numpy())}
    models = {"cop_map": cop_map, "cap_map": cap_map, "grey": grey, "expected_model": cfg.expected_model,
              "gbm_importance": {f: float(v) / tot for f, v in zip(GBM_FEATURES, imp)},
              "train_rows": int(tr.sum()), "test_rows": int(te_.sum()),
              "ranges": {c: [float(g[c].min()), float(g[c].max())] for c in ("t_evap_c", "t_cond_c", "plr", "ambient_temp_c", "coolant_supply_temp_c")}}
    return models, sc

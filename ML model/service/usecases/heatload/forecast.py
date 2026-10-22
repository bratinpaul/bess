"""Operational heat-load forecast (minutes to hours ahead) of the measured reference, by issue vintage.

At each issue time t and horizon h:
  plan       planned battery power over (t, t + h]: the EMS dispatch schedule (dispatch_event) where it covers the
             step, else the typical day (median setpoint per 5-min slot of the training days); or the realized power
             ("oracle": what a perfect schedule would give - the upper bound of plan value)
  drivers    current = plan / pack voltage, SOC rolled forward with the plan, ambient from the weather forecast (offset
             to the HVAC ambient sensor) else today's value + the typical diurnal swing, GHI forecast else clear-sky x
             the current clearness
  steady     the calibrated heat balance at t + h with those drivers (battery heat from the R(SOC, T) sub-model, PCS loss
             from its loss curve, solar, envelope, aux)
  physics    RC response: y(t+h) = steady(t+h) + (y(t) - steady(t)) · exp(-h / τ), τ fitted on the training issues
  hybrid     physics + LightGBM quantile models (P10 / P50 / P90) on the residual, with lagged load, plan and weather
  persistence y(t)
"""
from dataclasses import dataclass, field
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd

from usecases.heatload import balance as B
from usecases.heatload import data as D

STEP = D.STEP_MIN
QUANTILES = (0.1, 0.5, 0.9)


@dataclass
class ForecastSettings:
    horizons: list[int] = field(default_factory=lambda: [15, 30, 60, 120, 240])
    plan_source: str = "scheduled"        # scheduled | typical | oracle
    issue_every_min: int = 30             # test issues
    train_issue_every_min: int = 15
    n_estimators: int = 300
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_child_samples: int = 20


def _slot(ts: pd.DatetimeIndex) -> np.ndarray:
    return ((ts.hour * 60 + ts.minute) // STEP).to_numpy()


class Forecaster:
    def __init__(self, df: pd.DataFrame, info: dict, cal: dict, batt: dict, pcs: dict, m: D.HeatMaster,
                 sched_sp: np.ndarray, wxf: pd.DataFrame, cfg: ForecastSettings):
        self.df, self.info, self.cal, self.batt, self.pcs, self.m, self.cfg = df, info, cal, batt, pcs, m, cfg
        self.idx = pd.DatetimeIndex(df["ts"])
        tr = df[df["is_train"]]
        slot = _slot(pd.DatetimeIndex(tr["ts"]))
        n = 24 * 60 // STEP
        self.typical_plan = tr["p_term_kw"].groupby(slot).median().reindex(range(n)).interpolate(limit_direction="both").fillna(0).to_numpy()
        self.amb_profile = tr["t_amb_c"].groupby(slot).mean().reindex(range(n)).interpolate(limit_direction="both").fillna(25).to_numpy()
        self.sched = sched_sp
        self.wxf = wxf
        self.k = cal["coef"]
        self.idle = info["rated_kw"] * 0.01
        self.usable = m.base.usable_kwh or 1.0
        self.tau = 0.0
        self.models: dict = {}

    # ------------------------------------------------------------ drivers and steady state

    def plan(self, o: np.ndarray, steps: int) -> tuple[np.ndarray, np.ndarray]:
        """Planned battery power (kW) for steps 1..steps after each origin, and the schedule coverage."""
        idx = np.minimum(o[:, None] + np.arange(1, steps + 1)[None, :], len(self.df) - 1)
        if self.cfg.plan_source == "oracle":
            return self.df["p_term_kw"].to_numpy()[idx], np.ones(idx.shape)
        typical = self.typical_plan[_slot(self.idx)[idx]]
        if self.cfg.plan_source == "typical":
            return typical, np.zeros(idx.shape)
        sched = self.sched[idx]
        return np.where(np.isnan(sched), typical, sched), (~np.isnan(sched)).astype(float)

    def _weather(self, o: np.ndarray, k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Ambient and GHI forecast at origin + k steps."""
        df = self.df
        ts0 = self.idx[o]
        tt = ts0 + pd.to_timedelta(k * STEP, unit="min")
        amb0 = df["t_amb_c"].to_numpy()[o]
        amb = amb0 + self.amb_profile[_slot(tt)] - self.amb_profile[_slot(ts0)]
        clear0 = df["ghi_clear_wm2"].to_numpy()[o]
        ratio = np.where(clear0 > 50, np.clip(df["ghi_wm2"].to_numpy()[o] / np.maximum(clear0, 1), 0.2, 1.0), 1.0)
        ghi = D.clear_sky_ghi(pd.Series(tt), self.m.latitude, self.m.longitude) * ratio
        if not self.wxf.empty and df["ghi_source"].eq("measured").any():
            # latest forecast run issued at or before the origin, valid at the target hour (offset to the HVAC sensor)
            w = self.wxf
            runs = np.sort(w["issued_at"].unique())
            pos = np.searchsorted(runs, ts0.to_numpy(), side="right") - 1
            key = pd.DataFrame({"issued_at": np.where(pos >= 0, runs[np.maximum(pos, 0)], np.datetime64("NaT")),
                                "valid_at": tt.floor("h").tz_convert(D.TZ)})
            key["issued_at"] = pd.to_datetime(key["issued_at"], utc=True).dt.tz_convert(D.TZ)
            hit = key.merge(w.drop_duplicates(["issued_at", "valid_at"]), on=["issued_at", "valid_at"], how="left")
            wx0 = df["wx_temp_c"].to_numpy()[o]
            off = np.where(np.isfinite(wx0), amb0 - wx0, 0.0)
            ft, fg = hit["temp_c"].to_numpy(), hit["ghi_wm2"].to_numpy()
            amb = np.where(np.isfinite(ft), ft + off, amb)
            ghi = np.where(np.isfinite(fg), fg, ghi)
        return amb, ghi

    def steady(self, p_kw: np.ndarray, v_pack: np.ndarray, soc: np.ndarray, t_cell: np.ndarray, amb: np.ndarray,
               t_enc: np.ndarray, ghi: np.ndarray, aux: np.ndarray, dudt: np.ndarray) -> np.ndarray:
        k, info = self.k, self.info
        i = p_kw * 1000 / np.where(v_pack > 0, v_pack, np.nanmedian(v_pack))
        direction = np.where(p_kw > self.idle, "CHARGE", np.where(p_kw < -self.idle, "DISCHARGE", "IDLE"))
        irr = B.battery_irr(self.batt, direction, i, soc, t_cell)
        rev = i * (np.nan_to_num(t_cell, nan=25.0) + 273.15) * dudt * info["cells_series"] / 1000
        rev = np.where(direction == "IDLE", 0.0, rev)
        pcs = B.pcs_loss(self.pcs, p_kw, self.idle)
        solar = info["alpha_a_m2"] * ghi / 1000
        env = info["ua_kw_per_k"] * (amb - info["setpoint_c"])
        ki = np.where(direction == "CHARGE", k["irr_chg"], k["irr_dis"])
        return np.nan_to_num(k["const"] + ki * irr + k["rev"] * rev + k["pcs"] * pcs + k["solar"] * solar + k["env"] * env + aux)

    def now_steady(self, o: np.ndarray) -> np.ndarray:
        df = self.df
        g = lambda c: df[c].to_numpy()[o]
        return self.steady(g("p_term_kw"), g("pack_voltage_v"), g("soc_pct"), g("cell_temp_avg_c"), g("t_amb_c"),
                           g("t_enc_c"), g("ghi_wm2"), g("q_aux_kw"), g("dudt_v_k"))

    # ------------------------------------------------------------ rows

    def rows(self, o: np.ndarray, with_target: bool = True) -> pd.DataFrame:
        df = self.df
        hs = np.array(self.cfg.horizons)
        steps = hs // STEP
        plan, cover = self.plan(o, int(steps.max()))
        n, m = len(o), len(steps)
        oo, kk, rr = np.repeat(o, m), np.tile(steps, n), np.repeat(np.arange(n), m)
        p_h = plan[rr, kk - 1]
        soc0 = df["soc_pct"].to_numpy()[oo]
        soc_h = np.clip(soc0 + np.cumsum(plan, axis=1)[rr, kk - 1] * STEP / 60 / self.usable * 100, 0, 100)
        amb, ghi = self._weather(oo, kk)
        g = lambda c: df[c].to_numpy()[oo]
        ss_h = self.steady(p_h, g("pack_voltage_v"), soc_h, g("cell_temp_avg_c"), amb, g("t_enc_c"), ghi, g("q_aux_kw"),
                           g("dudt_v_k"))
        ss_0 = self.now_steady(oo)
        y0 = g("measured_kw")
        physics = self.relax(ss_h, ss_0, y0, kk)
        y = df["measured_kw"].to_numpy()
        roll = pd.Series(y).rolling(12, min_periods=3).mean().to_numpy()
        csum = np.cumsum(np.abs(plan), axis=1)
        out = pd.DataFrame({
            "h_min": kk * STEP, "y0": y0, "dy_5": y0 - y[np.maximum(oo - 1, 0)], "dy_30": y0 - y[np.maximum(oo - 6, 0)],
            "roll_1h": roll[oo], "ss0": ss_0, "ss_h": ss_h, "physics": physics, "plan_h": p_h / self.info["rated_kw"],
            "plan_mean": csum[rr, kk - 1] / kk / self.info["rated_kw"], "plan_cov": cover[rr, :].mean(axis=1),
            "p0": g("p_term_kw") / self.info["rated_kw"], "soc0": soc0, "soc_h": soc_h, "amb_h": amb, "ghi_h": ghi,
            "t_enc0": g("t_enc_c"), "t_cell0": g("cell_temp_avg_c"), "hour_t": (self.idx[oo] + pd.to_timedelta(kk * STEP, unit="min")).hour.to_numpy(),
            "hvac0": g("hvac_kw"),
        })
        out["pos"], out["step"] = oo, kk
        out["issued_at"] = self.idx[oo]
        out["valid_at"] = self.idx[oo] + pd.to_timedelta(kk * STEP, unit="min")
        out["plan_kw"] = p_h
        if with_target:
            tgt = np.minimum(oo + kk, len(df) - 1)
            gap = (self.idx[tgt] - pd.DatetimeIndex(out["valid_at"])).total_seconds().to_numpy()
            out["actual"] = np.where(np.abs(gap) < 60, y[tgt], np.nan)
            out["persistence"] = y0
        return out

    def relax(self, ss_h, ss_0, y0, kk) -> np.ndarray:
        decay = np.exp(-kk * STEP / self.tau) if self.tau > 0 else np.zeros(len(kk))
        return ss_h + (y0 - ss_0) * decay

    FEATURES = ["h_min", "y0", "dy_5", "dy_30", "roll_1h", "ss0", "ss_h", "physics", "plan_h", "plan_mean", "plan_cov",
                "p0", "soc0", "soc_h", "amb_h", "ghi_h", "t_enc0", "t_cell0", "hour_t", "hvac0"]

    def origins(self, train: bool) -> np.ndarray:
        every = (self.cfg.train_issue_every_min if train else self.cfg.issue_every_min) // STEP
        max_steps = max(self.cfg.horizons) // STEP
        mask = self.df["is_train"].to_numpy() if train else ~self.df["is_train"].to_numpy()
        pos = np.flatnonzero(mask)
        pos = pos[(pos >= 6) & (pos < len(self.df) - max_steps)]
        if not train:
            pos = pos[self.idx[pos].minute.to_numpy() % self.cfg.issue_every_min == 0]
        return pos[::max(1, every)] if train else pos

    def fit(self) -> dict:
        o = self.origins(train=True)
        if len(o) < 50:
            raise D.HeatLoadError("Too few training issues for the forecast (widen the window)")
        # τ: the RC lag that best explains the training issues
        best = (np.inf, 0.0)
        r = self.rows(o).dropna(subset=["actual"]).reset_index(drop=True)
        for tau in [0.0, 5, 10, 15, 30, 60, 120, 240]:
            self.tau = tau
            phys = self.relax(r["ss_h"].to_numpy(), r["ss0"].to_numpy(), r["y0"].to_numpy(), r["step"].to_numpy())
            mae = float(np.mean(np.abs(phys - r["actual"].to_numpy())))
            if mae < best[0]:
                best = (mae, tau)
        self.tau = best[1]
        r["physics"] = self.relax(r["ss_h"].to_numpy(), r["ss0"].to_numpy(), r["y0"].to_numpy(), r["step"].to_numpy())
        resid = (r["actual"] - r["physics"]).to_numpy()
        for q in QUANTILES:
            mdl = lgb.LGBMRegressor(objective="quantile", alpha=q, n_estimators=self.cfg.n_estimators,
                                    learning_rate=self.cfg.learning_rate, num_leaves=self.cfg.num_leaves,
                                    min_child_samples=self.cfg.min_child_samples, subsample=0.9, subsample_freq=1,
                                    colsample_bytree=0.9, random_state=42, verbose=-1, n_jobs=4)
            mdl.fit(r[self.FEATURES], resid)
            self.models[q] = mdl
        imp = self.models[0.5].booster_.feature_importance(importance_type="gain")
        tot = float(imp.sum()) or 1.0
        return {"tau_min": self.tau, "tau_grid_mae": best[0], "train_rows": int(len(r)),
                "importance": dict(sorted(((f, float(v) / tot) for f, v in zip(self.FEATURES, imp)), key=lambda x: -x[1]))}

    def predict(self, r: pd.DataFrame) -> pd.DataFrame:
        X = r[self.FEATURES]
        q = {qq: self.models[qq].predict(X) for qq in QUANTILES}
        p10, p50, p90 = (r["physics"].to_numpy() + q[x] for x in QUANTILES)
        lo, hi = np.minimum.reduce([p10, p50, p90]), np.maximum.reduce([p10, p50, p90])
        r = r.copy()
        r["p50"] = np.clip(p50, 0, None)
        r["p10"] = np.clip(lo, 0, None)
        r["p90"] = np.clip(hi, 0, None)
        r["physics"] = np.clip(r["physics"], 0, None)
        return r

    def backtest(self) -> tuple[pd.DataFrame, dict]:
        o = self.origins(train=False)
        if not len(o):
            return pd.DataFrame(), {}
        r = self.predict(self.rows(o)).dropna(subset=["actual"])
        thr = float(np.nanpercentile(self.df.loc[self.df["is_train"], "measured_kw"], 90))
        scores = {}
        for h, g in r.groupby("h_min"):
            a = g["actual"].to_numpy()
            row = {"n": int(len(g))}
            for name in ("persistence", "physics", "p50"):
                e = g[name].to_numpy() - a
                row[f"{name}_mae"] = float(np.mean(np.abs(e)))
                row[f"{name}_rmse"] = float(np.sqrt(np.mean(e ** 2)))
            pin = []
            for qq, col in ((0.1, "p10"), (0.5, "p50"), (0.9, "p90")):
                d = a - g[col].to_numpy()
                pin.append(np.mean(np.maximum(qq * d, (qq - 1) * d)))
            row["pinball"] = float(np.mean(pin))
            row["coverage_p10_p90"] = float(np.mean((a >= g["p10"]) & (a <= g["p90"])))
            row["skill_vs_persistence"] = 1 - row["p50_mae"] / row["persistence_mae"] if row["persistence_mae"] else None
            hot = a > thr
            row["high_load_events"] = int(hot.sum())
            row["high_load_recall_p90"] = float(np.mean(g["p90"].to_numpy()[hot] > thr)) if hot.any() else None
            scores[int(h)] = row
        return r, {"by_horizon": scores, "high_load_threshold_kw": thr, "issues": int(len(o))}
